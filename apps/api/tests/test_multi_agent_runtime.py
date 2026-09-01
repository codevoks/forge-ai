from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import pytest
from conftest import auth_headers
from fastapi.testclient import TestClient

from forge_api.api.errors import ProblemError
from forge_api.application.agent_runtime import AgentRuntime
from forge_api.application.multi_agent_comparison_service import MultiAgentComparisonService
from forge_api.application.multi_agent_router import apply_router
from forge_api.application.reliability_service import OutboxDispatcher, WorkerConsumer
from forge_api.config import Settings
from forge_api.domain.identity import ActorContext, Role
from forge_api.domain.reliability import RetryPolicy
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.dev_issuer import DevIssuer
from forge_api.infrastructure.queue import InMemoryQueue
from forge_api.infrastructure.workflow_repositories import WorkflowRepository
from forge_api.scripts.seed import TENANT_ID, WORKSPACE_ID

DEPLOYMENT_AND_CUSTOMER_OBJECTIVE = (
    "Investigate why the API deployment is slow and customers are complaining."
)
REMEDIATION_OBJECTIVE = "We need to remediate and fix this ticket with a mitigation plan."
NO_SIGNAL_OBJECTIVE = "Please take a comprehensive look at everything."


def headers(issuer: DevIssuer, subject: str = "alice", key: str | None = None) -> dict[str, str]:
    request_headers = auth_headers(issuer, subject)
    if key:
        request_headers["Idempotency-Key"] = key
    return request_headers


def actor_for(database: Database, settings: Settings, subject: str, role: Role) -> ActorContext:
    with database.transaction(actor_id="00000000-0000-0000-0000-000000000000") as conn:
        row = conn.execute(
            "select id from users where external_issuer = %s and external_subject = %s",
            (settings.oidc_issuer, f"oidc|{subject}"),
        ).fetchone()
    assert row is not None
    return ActorContext(
        user_id=str(row["id"]),
        external_subject=f"oidc|{subject}",
        email=f"{subject}@forge.local",
        display_name=subject.title(),
        tenant_ids=frozenset({TENANT_ID}),
        workspace_roles={WORKSPACE_ID: role},
    )


@pytest.fixture
def alice(database: Database, settings: Settings) -> ActorContext:
    return actor_for(database, settings, "alice", Role.TENANT_ADMIN)


@pytest.fixture
def ava(database: Database, settings: Settings) -> ActorContext:
    return actor_for(database, settings, "ava", Role.APPROVER)


def create_multi_agent_run(
    client: TestClient, issuer: DevIssuer, *, objective: str, key: str
) -> Mapping[str, Any]:
    workflows = client.get("/v1/workflows", headers=headers(issuer)).json()["workflow_versions"]
    workflow = next(w for w in workflows if w["name"] == "Multi-Agent Investigation Demo")
    response = client.post(
        "/v1/runs",
        headers=headers(issuer, key=key),
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": objective,
            "strategy_kind": "multi_agent_parallel",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["run"]


def run_worker_until_terminal(
    *,
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
    run_id: str,
    auto_approve: bool = True,
    max_ticks: int = 60,
) -> Mapping[str, Any]:
    queue = InMemoryQueue()
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    consumer = WorkerConsumer(
        database=database,
        queue=queue,
        worker_id=settings.worker_id,
        lease_seconds=settings.task_lease_seconds,
        retry_policy=RetryPolicy(max_attempts=settings.task_max_attempts),
    )
    run: Mapping[str, Any] = {}
    for _ in range(max_ticks):
        dispatcher.dispatch_once()
        outcome = consumer.consume_once(block_ms=0)
        if auto_approve and outcome == "waiting_approval":
            approvals = client.get(
                "/v1/approvals", headers=headers(issuer, "ava")
            ).json()["approval_requests"]
            for approval in approvals:
                if approval["run_id"] != run_id or approval["status"] != "pending":
                    continue
                approved = client.post(
                    f"/v1/approvals/{approval['id']}:approve",
                    headers=headers(issuer, "ava", f"approve-{uuid4()}")
                    | {"If-Match": str(approval["request_version"])},
                    json={"reason": "Ava approves the specialist's simulated effect."},
                )
                assert approved.status_code == 200, approved.text
        run = client.get(f"/v1/runs/{run_id}", headers=headers(issuer)).json()["run"]
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            return run
    raise AssertionError("run did not become terminal")


# -- router-driven fan-out through the real run/worker path -------------------------


def test_multi_agent_run_routes_and_fans_out_in_parallel(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    run = create_multi_agent_run(
        client,
        issuer,
        objective=DEPLOYMENT_AND_CUSTOMER_OBJECTIVE,
        key=f"multi-run-{uuid4()}",
    )
    assert run["strategy_kind"] == "multi_agent_parallel"
    routing = run["strategy_metadata"]["routing_decision"]
    selected_roles = {s["role"] for s in routing["specialists"] if s["selected"]}
    assert selected_roles == {"deployment_specialist", "customer_impact_specialist"}
    assert routing["fallback_selected_all"] is False

    tasks = client.get(f"/v1/runs/{run['id']}/tasks", headers=headers(issuer)).json()["tasks"]
    step_keys = {t["step_key"] for t in tasks}
    assert step_keys == {
        "deployment_specialist",
        "customer_impact_specialist",
        "synthesize_findings",
    }
    assert "remediation_specialist" not in step_keys

    completed = run_worker_until_terminal(
        database=database, settings=settings, client=client, issuer=issuer, run_id=run["id"]
    )
    assert completed["status"] == "succeeded"

    tasks = client.get(f"/v1/runs/{run['id']}/tasks", headers=headers(issuer)).json()["tasks"]
    synthesis = next(t for t in tasks if t["step_key"] == "synthesize_findings")
    assert synthesis["result"]["mode"] == "multi_agent_synthesis"
    assert synthesis["result"]["partial_failure"] is False
    assert len(synthesis["result"]["specialist_results"]) == 2


def test_multi_agent_run_falls_back_to_all_specialists_without_a_clear_signal(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    run = create_multi_agent_run(
        client, issuer, objective=NO_SIGNAL_OBJECTIVE, key=f"multi-fallback-{uuid4()}"
    )
    routing = run["strategy_metadata"]["routing_decision"]
    assert routing["fallback_selected_all"] is True
    tasks = client.get(f"/v1/runs/{run['id']}/tasks", headers=headers(issuer)).json()["tasks"]
    assert {t["step_key"] for t in tasks} == {
        "deployment_specialist",
        "customer_impact_specialist",
        "remediation_specialist",
        "synthesize_findings",
    }

    completed = run_worker_until_terminal(
        database=database, settings=settings, client=client, issuer=issuer, run_id=run["id"]
    )
    assert completed["status"] == "succeeded"


def test_remediation_specialist_requires_exact_action_approval(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    run = create_multi_agent_run(
        client, issuer, objective=REMEDIATION_OBJECTIVE, key=f"multi-remediation-{uuid4()}"
    )
    tasks = client.get(f"/v1/runs/{run['id']}/tasks", headers=headers(issuer)).json()["tasks"]
    assert {t["step_key"] for t in tasks} == {"remediation_specialist", "synthesize_findings"}

    completed = run_worker_until_terminal(
        database=database, settings=settings, client=client, issuer=issuer, run_id=run["id"]
    )
    assert completed["status"] == "succeeded"
    invocations = client.get(
        f"/v1/tools/runs/{run['id']}/invocations", headers=headers(issuer)
    ).json()["tool_invocations"]
    assert any(inv["risk"] == "simulated_effect" for inv in invocations)


# -- isolation ------------------------------------------------------------------


def test_specialist_evidence_is_isolated_per_task(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    run = create_multi_agent_run(
        client,
        issuer,
        objective=DEPLOYMENT_AND_CUSTOMER_OBJECTIVE,
        key=f"multi-isolation-{uuid4()}",
    )
    run_worker_until_terminal(
        database=database, settings=settings, client=client, issuer=issuer, run_id=run["id"]
    )
    system_actor_id = "00000000-0000-0000-0000-000000000000"
    with database.transaction(tenant_id=TENANT_ID, actor_id=system_actor_id) as conn:
        rows = conn.execute(
            "select distinct task_id from evidence_items where run_id = %s", (run["id"],)
        ).fetchall()
    # Two specialists collected evidence into two distinct tasks, never a
    # shared/run-wide pool.
    assert len({str(row["task_id"]) for row in rows}) == 2


def test_specialist_cannot_use_a_tool_outside_its_own_role_grant(
    database: Database, settings: Settings
) -> None:
    """A specialist's task-level allowed_tools is the real boundary, independent
    of what any sibling specialist in the same run was granted."""
    from forge_api.application.tool_runtime import ToolRuntime

    runtime = ToolRuntime(database=database)
    fake_claim = {
        "worker_id": "test-worker",
        "tenant_id": TENANT_ID,
        "workspace_id": WORKSPACE_ID,
        "run_id": "018f0000-0000-7000-8000-0000000000fa",
        "task_id": "018f0000-0000-7000-8000-0000000000fb",
        "attempt_id": None,
        "input": {
            "tool_name": "customer_reports.search",
            "tool_version": 1,
            "arguments": {"product_area": "worker", "severity": "medium"},
        },
    }
    with pytest.raises(ProblemError) as exc_info:
        runtime.invoke_for_claim(fake_claim)
    assert exc_info.value.code == "tool_not_granted"


# -- partial failure / all-fail aggregation ------------------------------------


def _publish_partial_failure_workflow(
    database: Database, actor: ActorContext, *, both_fail: bool
) -> Mapping[str, Any]:
    budgets = {
        "max_iterations": 1,
        "max_tool_calls": 1,
        "max_model_calls": 1,
        "max_context_items": 4,
        "max_invalid_decisions": 1,
        "max_no_progress_decisions": 1,
        "max_output_tokens": 800,
    }
    good_scenario = "step_limit" if both_fail else "success"
    steps = [
        {
            "key": "spec_a",
            "name": "Specialist A",
            "kind": "agent",
            "input": {
                "scenario": "step_limit",
                "objective": "Loop until the budget stops it.",
                "agent_role": "deployment_specialist",
                "allowed_tools": [{"tool_name": "deployment_history.lookup", "tool_version": 1}],
                "budgets": budgets,
            },
        },
        {
            "key": "spec_b",
            "name": "Specialist B",
            "kind": "agent",
            "input": {
                "scenario": good_scenario,
                "objective": "Investigate customer impact.",
                "agent_role": "customer_impact_specialist",
                "allowed_tools": [{"tool_name": "customer_reports.search", "tool_version": 1}],
                "budgets": {**budgets, "max_iterations": 4, "max_model_calls": 4},
            },
        },
        {
            "key": "synth",
            "name": "Synthesize",
            "kind": "deterministic",
            "input": {"mode": "multi_agent_synthesize"},
        },
    ]
    with database.transaction(tenant_id=TENANT_ID, actor_id=actor.user_id) as conn:
        return WorkflowRepository(conn).create_published_version(
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            actor_id=actor.user_id,
            name=f"Partial Failure Test {uuid4()}",
            steps=steps,
            edges=[{"from": "spec_a", "to": "synth"}, {"from": "spec_b", "to": "synth"}],
        )


def test_one_specialist_safe_failure_yields_partial_synthesis(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    workflow = _publish_partial_failure_workflow(database, alice, both_fail=False)
    from forge_api.infrastructure.workflow_repositories import RunRepository

    with database.transaction(tenant_id=TENANT_ID, actor_id=alice.user_id) as conn:
        run = RunRepository(conn).create_run(
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            actor_id=alice.user_id,
            workflow_version=workflow,
            objective="Partial failure scenario.",
            constraints={},
            strategy_kind="multi_agent_parallel",
            strategy_version="multi-agent-parallel-v1",
        )
    terminal = _drive(database, settings, alice, str(run["id"]))
    assert terminal == "succeeded"
    with database.transaction(actor_id=alice.user_id) as conn:
        synth = conn.execute(
            "select result from tasks where run_id = %s and step_key = 'synth'", (run["id"],)
        ).fetchone()
    assert synth is not None
    assert synth["result"]["partial_failure"] is True
    assert "deployment_specialist" in synth["result"]["skipped_roles"]


def test_all_specialists_safe_failure_fails_the_run(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    workflow = _publish_partial_failure_workflow(database, alice, both_fail=True)
    from forge_api.infrastructure.workflow_repositories import RunRepository

    with database.transaction(tenant_id=TENANT_ID, actor_id=alice.user_id) as conn:
        run = RunRepository(conn).create_run(
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            actor_id=alice.user_id,
            workflow_version=workflow,
            objective="All specialists fail.",
            constraints={},
            strategy_kind="multi_agent_parallel",
            strategy_version="multi-agent-parallel-v1",
        )
    terminal = _drive(database, settings, alice, str(run["id"]))
    assert terminal == "failed"


def _drive(database: Database, settings: Settings, actor: ActorContext, run_id: str) -> str:
    queue = InMemoryQueue()
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    consumer = WorkerConsumer(
        database=database,
        queue=queue,
        worker_id=settings.worker_id,
        lease_seconds=settings.task_lease_seconds,
        retry_policy=RetryPolicy(max_attempts=settings.task_max_attempts),
    )
    from forge_api.infrastructure.workflow_repositories import RunRepository

    status = "running"
    for _ in range(60):
        dispatcher.dispatch_once()
        consumer.consume_once(block_ms=0)
        with database.transaction(actor_id=actor.user_id) as conn:
            run = RunRepository(conn).get_run_for_actor(actor_id=actor.user_id, run_id=run_id)
        status = str(run["status"])
        if status in {"succeeded", "failed", "cancelled"}:
            return status
    return status


# -- publish-time / router bounds ------------------------------------------------


def test_apply_router_rejects_too_few_specialists() -> None:
    workflow_version = {
        "steps": [
            {
                "key": "only_one",
                "name": "Only one",
                "kind": "agent",
                "input": {"agent_role": "deployment_specialist"},
            }
        ],
        "edges": [],
    }
    with pytest.raises(ProblemError) as exc_info:
        apply_router(workflow_version=workflow_version, objective="deploy")
    assert exc_info.value.code == "multi_agent_workflow_invalid"


def test_apply_router_rejects_too_many_specialists() -> None:
    steps = [
        {
            "key": f"spec_{i}",
            "name": f"Specialist {i}",
            "kind": "agent",
            "input": {"agent_role": "deployment_specialist"},
        }
        for i in range(6)
    ]
    with pytest.raises(ProblemError) as exc_info:
        apply_router(workflow_version={"steps": steps, "edges": []}, objective="deploy")
    assert exc_info.value.code == "multi_agent_workflow_invalid"


# -- cancellation propagation ----------------------------------------------------


def test_cancellation_propagates_to_pending_specialists_and_synthesizer(
    client: TestClient, issuer: DevIssuer
) -> None:
    run = create_multi_agent_run(
        client,
        issuer,
        objective=DEPLOYMENT_AND_CUSTOMER_OBJECTIVE,
        key=f"multi-cancel-{uuid4()}",
    )
    cancelled = client.post(
        f"/v1/runs/{run['id']}:cancel",
        headers=headers(issuer),
        json={"reason": "Cancel mid-fan-out before any worker tick."},
    )
    assert cancelled.status_code == 200
    tasks = client.get(f"/v1/runs/{run['id']}/tasks", headers=headers(issuer)).json()["tasks"]
    assert all(t["status"] == "cancelled" for t in tasks)


# -- debugger compatibility (Phase 10) -------------------------------------------


def test_debugger_snapshot_works_for_a_completed_multi_agent_run(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    run = create_multi_agent_run(
        client,
        issuer,
        objective=DEPLOYMENT_AND_CUSTOMER_OBJECTIVE,
        key=f"multi-debugger-{uuid4()}",
    )
    run_worker_until_terminal(
        database=database, settings=settings, client=client, issuer=issuer, run_id=run["id"]
    )
    snapshot = client.get(f"/v1/runs/{run['id']}/debugger", headers=headers(issuer))
    assert snapshot.status_code == 200
    body = snapshot.json()["debugger"]
    assert body["run"]["id"] == run["id"]
    assert len(body["tasks"]) == 3


# -- comparative evaluator --------------------------------------------------------


def test_strategy_comparison_reports_metrics_for_both_strategies(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MultiAgentComparisonService(database, settings)
    result = service.run_comparison(alice, WORKSPACE_ID, f"cmp-{uuid4()}")
    comparison = result["strategy_comparison"]
    metrics = comparison["metrics"]
    assert metrics["single_agentic"]["terminal_status"] == "succeeded"
    assert metrics["multi_agent_parallel"]["terminal_status"] == "succeeded"
    assert metrics["multi_agent_parallel"]["task_status_counts"]["succeeded"] == 3
    assert metrics["single_agentic"]["task_status_counts"]["succeeded"] == 1
    assert comparison["caveats"]


def test_strategy_comparison_is_idempotent(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MultiAgentComparisonService(database, settings)
    key = f"cmp-idem-{uuid4()}"
    first = service.run_comparison(alice, WORKSPACE_ID, key)
    second = service.run_comparison(alice, WORKSPACE_ID, key)
    assert first["strategy_comparison"]["id"] == second["strategy_comparison"]["id"]


def test_single_agent_runtime_unchanged_for_existing_bounded_agent_demo(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    """Phase 7's existing single-agent workflow behaves identically after the
    Phase 12 generalization of the fake model's default tool-selection."""
    workflows = client.get("/v1/workflows", headers=headers(issuer)).json()["workflow_versions"]
    workflow = next(w for w in workflows if w["name"] == "Bounded Agent Demo")
    response = client.post(
        "/v1/runs",
        headers=headers(issuer, key=f"single-unchanged-{uuid4()}"),
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Investigate the local deployment signal.",
        },
    )
    assert response.status_code == 201
    run = response.json()["run"]
    assert run["strategy_kind"] == "single_agentic"
    queue = InMemoryQueue()
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    consumer = WorkerConsumer(
        database=database,
        queue=queue,
        worker_id=settings.worker_id,
        lease_seconds=settings.task_lease_seconds,
        retry_policy=RetryPolicy(max_attempts=settings.task_max_attempts),
    )
    for _ in range(20):
        dispatcher.dispatch_once()
        consumer.consume_once(block_ms=0)
        current = client.get(f"/v1/runs/{run['id']}", headers=headers(issuer)).json()["run"]
        if current["status"] in {"succeeded", "failed", "cancelled"}:
            break
    assert current["status"] == "succeeded"
    invocations = client.get(
        f"/v1/tools/runs/{run['id']}/invocations", headers=headers(issuer)
    ).json()["tool_invocations"]
    assert {inv["tool_name"] for inv in invocations} == {"deployment_history.lookup"}


def test_agent_runtime_reused_directly_still_works(database: Database) -> None:
    """Sanity: AgentRuntime import path unaffected by Phase 12 additions."""
    runtime = AgentRuntime(database=database)
    assert runtime.model is not None
