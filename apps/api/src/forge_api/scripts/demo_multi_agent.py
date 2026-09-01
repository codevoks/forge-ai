import json
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from redis import Redis

from forge_api.api.errors import ProblemError
from forge_api.application.approval_service import ApprovalService
from forge_api.application.multi_agent_comparison_service import MultiAgentComparisonService
from forge_api.application.reliability_service import OutboxDispatcher, WorkerConsumer
from forge_api.application.run_service import RunService
from forge_api.config import Settings
from forge_api.domain.approvals import ApprovalDecisionValue
from forge_api.domain.identity import ActorContext, Role
from forge_api.domain.reliability import RetryPolicy
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.queue import InMemoryQueue
from forge_api.infrastructure.workflow_repositories import RunRepository, WorkflowRepository
from forge_api.scripts.seed import TENANT_ID, WORKSPACE_ID
from forge_api.scripts.seed import main as seed_main

DEPLOYMENT_AND_CUSTOMER_OBJECTIVE = (
    "Investigate why the API deployment is slow and customers are complaining."
)
REMEDIATION_OBJECTIVE = "We need to remediate and fix this ticket with a mitigation plan."
NO_SIGNAL_OBJECTIVE = "Please take a comprehensive look at everything."


def _assert_local_url(url: str, *, label: str) -> None:
    parsed = urlparse(url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(f"{label} must point at a loopback host for this demo.")


def _print(action: str, result: dict[str, Any]) -> None:
    print(json.dumps({"action": action, "result": result}, sort_keys=True, default=str))


def _user_id(database: Database, settings: Settings, subject: str) -> str:
    with database.transaction(actor_id="00000000-0000-0000-0000-000000000000") as conn:
        row = conn.execute(
            "select id from users where external_issuer = %s and external_subject = %s",
            (settings.oidc_issuer, f"oidc|{subject}"),
        ).fetchone()
    if row is None:
        raise RuntimeError(f"Seeded {subject} user was not found.")
    return str(row["id"])


def _actor(database: Database, settings: Settings, subject: str, role: Role) -> ActorContext:
    return ActorContext(
        user_id=_user_id(database, settings, subject),
        external_subject=f"oidc|{subject}",
        email=f"{subject}@forge.local",
        display_name=f"{subject.title()} Demo",
        tenant_ids=frozenset({TENANT_ID}),
        workspace_roles={WORKSPACE_ID: role},
    )


def _clear_queue(settings: Settings) -> None:
    Redis.from_url(settings.redis_url, decode_responses=True).delete(settings.queue_stream)


def _create_run(
    run_service: RunService, actor: ActorContext, *, objective: str, strategy_kind: str, key: str
) -> dict[str, Any]:
    with run_service.database.transaction(actor_id=actor.user_id) as conn:
        versions = WorkflowRepository(conn).list_versions_for_actor(actor_id=actor.user_id)
    workflow = next(v for v in versions if v["name"] == "Multi-Agent Investigation Demo")
    result = run_service.create(
        actor,
        key,
        {
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": objective,
            "strategy_kind": strategy_kind,
        },
    )
    return dict(result["run"])


def _drive_worker(
    *,
    database: Database,
    settings: Settings,
    actor: ActorContext,
    approver: ActorContext,
    run_id: str,
) -> str:
    queue = InMemoryQueue()
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    consumer = WorkerConsumer(
        database=database,
        queue=queue,
        worker_id=settings.worker_id,
        lease_seconds=settings.task_lease_seconds,
        retry_policy=RetryPolicy(max_attempts=settings.task_max_attempts),
    )
    run_service = RunService(database)
    for _ in range(60):
        dispatcher.dispatch_once()
        outcome = consumer.consume_once(block_ms=50)
        if outcome == "waiting_approval":
            approvals = ApprovalService(database).list_approvals(approver)
            for approval in approvals:
                if approval["run_id"] != run_id or approval["status"] != "pending":
                    continue
                ApprovalService(database).decide(
                    approver,
                    str(approval["id"]),
                    decision=ApprovalDecisionValue.APPROVED,
                    reason="Ava approves the specialist's simulated remediation effect.",
                    expected_version=int(approval["request_version"]),
                    idempotency_key=f"demo-multi-approve-{approval['id']}",
                )
        run = run_service.get(actor, run_id)
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            return str(run["status"])
    return str(run_service.get(actor, run_id)["status"])


def demo_router_fans_out_and_synthesizes(
    database: Database, settings: Settings, alice: ActorContext, ava: ActorContext
) -> None:
    run_service = RunService(database)
    run = _create_run(
        run_service,
        alice,
        objective=DEPLOYMENT_AND_CUSTOMER_OBJECTIVE,
        strategy_kind="multi_agent_parallel",
        key=f"demo-multi-fanout-{uuid4()}",
    )
    routing = run["strategy_metadata"]["routing_decision"]
    tasks = run_service.list_tasks(alice, run["id"])
    _print(
        "multi_agent_router_selected_specialists",
        {
            "objective": DEPLOYMENT_AND_CUSTOMER_OBJECTIVE,
            "selected_roles": sorted(
                s["role"] for s in routing["specialists"] if s["selected"]
            ),
            "skipped_roles": sorted(
                s["role"] for s in routing["specialists"] if not s["selected"]
            ),
            "tasks_created": sorted(t["step_key"] for t in tasks),
        },
    )

    status = _drive_worker(
        database=database, settings=settings, actor=alice, approver=ava, run_id=run["id"]
    )
    tasks = run_service.list_tasks(alice, run["id"])
    synthesis = next(t for t in tasks if t["step_key"] == "synthesize_findings")
    with database.transaction(tenant_id=TENANT_ID, actor_id=alice.user_id) as conn:
        evidence_task_ids = conn.execute(
            "select distinct task_id from evidence_items where run_id = %s", (run["id"],)
        ).fetchall()
    _print(
        "multi_agent_parallel_fanout_and_synthesis",
        {
            "terminal_status": status,
            "specialist_results": [
                {
                    "role": r["role"],
                    "outcome": r["outcome"],
                }
                for r in synthesis["result"]["specialist_results"]
            ],
            "partial_failure": synthesis["result"]["partial_failure"],
            "distinct_specialist_evidence_tasks": len(evidence_task_ids),
            "paid_provider_calls": 0,
        },
    )


def demo_fallback_selects_all_specialists(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    run_service = RunService(database)
    run = _create_run(
        run_service,
        alice,
        objective=NO_SIGNAL_OBJECTIVE,
        strategy_kind="multi_agent_parallel",
        key=f"demo-multi-fallback-{uuid4()}",
    )
    routing = run["strategy_metadata"]["routing_decision"]
    _print(
        "multi_agent_router_fallback_selected_all",
        {
            "objective": NO_SIGNAL_OBJECTIVE,
            "fallback_selected_all": routing["fallback_selected_all"],
            "selected_role_count": sum(1 for s in routing["specialists"] if s["selected"]),
        },
    )


def demo_approval_gated_specialist(
    database: Database, settings: Settings, alice: ActorContext, ava: ActorContext
) -> None:
    run_service = RunService(database)
    run = _create_run(
        run_service,
        alice,
        objective=REMEDIATION_OBJECTIVE,
        strategy_kind="multi_agent_parallel",
        key=f"demo-multi-approval-{uuid4()}",
    )
    status = _drive_worker(
        database=database, settings=settings, actor=alice, approver=ava, run_id=run["id"]
    )
    with database.transaction(actor_id=alice.user_id) as conn:
        invocation = conn.execute(
            "select risk, status from tool_invocations "
            "where run_id = %s and risk = 'simulated_effect'",
            (run["id"],),
        ).fetchone()
    _print(
        "multi_agent_specialist_required_exact_action_approval",
        {
            "terminal_status": status,
            "simulated_effect_invocation_status": invocation["status"] if invocation else None,
        },
    )


def demo_partial_and_total_failure(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    budgets = {
        "max_iterations": 1,
        "max_tool_calls": 1,
        "max_model_calls": 1,
        "max_context_items": 4,
        "max_invalid_decisions": 1,
        "max_no_progress_decisions": 1,
        "max_output_tokens": 800,
    }

    def publish(*, both_fail: bool) -> dict[str, Any]:
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
                    "allowed_tools": [
                        {"tool_name": "deployment_history.lookup", "tool_version": 1}
                    ],
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
        with database.transaction(tenant_id=TENANT_ID, actor_id=alice.user_id) as conn:
            return WorkflowRepository(conn).create_published_version(
                tenant_id=TENANT_ID,
                workspace_id=WORKSPACE_ID,
                actor_id=alice.user_id,
                name=f"Demo Failure Scenario {uuid4()}",
                steps=steps,
                edges=[{"from": "spec_a", "to": "synth"}, {"from": "spec_b", "to": "synth"}],
            )

    def run_and_drive(workflow: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
        with database.transaction(tenant_id=TENANT_ID, actor_id=alice.user_id) as conn:
            run = RunRepository(conn).create_run(
                tenant_id=TENANT_ID,
                workspace_id=WORKSPACE_ID,
                actor_id=alice.user_id,
                workflow_version=workflow,
                objective="Failure scenario demonstration.",
                constraints={},
                strategy_kind="multi_agent_parallel",
                strategy_version="multi-agent-parallel-v1",
            )
        queue = InMemoryQueue()
        dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
        consumer = WorkerConsumer(
            database=database,
            queue=queue,
            worker_id=settings.worker_id,
            lease_seconds=settings.task_lease_seconds,
            retry_policy=RetryPolicy(max_attempts=settings.task_max_attempts),
        )
        status = "running"
        for _ in range(30):
            dispatcher.dispatch_once()
            consumer.consume_once(block_ms=0)
            with database.transaction(actor_id=alice.user_id) as conn:
                current = RunRepository(conn).get_run_for_actor(
                    actor_id=alice.user_id, run_id=str(run["id"])
                )
            status = str(current["status"])
            if status in {"succeeded", "failed", "cancelled"}:
                break
        with database.transaction(actor_id=alice.user_id) as conn:
            synth_row = conn.execute(
                "select result from tasks where run_id = %s and step_key = 'synth'",
                (run["id"],),
            ).fetchone()
        return status, (synth_row["result"] if synth_row else None)

    partial_status, partial_result = run_and_drive(publish(both_fail=False))
    _print(
        "multi_agent_partial_failure_aggregation",
        {
            "terminal_status": partial_status,
            "partial_failure": partial_result["partial_failure"] if partial_result else None,
            "skipped_roles": partial_result["skipped_roles"] if partial_result else None,
        },
    )

    total_status, _ = run_and_drive(publish(both_fail=True))
    _print(
        "multi_agent_all_specialists_fail_closes_the_run",
        {"terminal_status": total_status},
    )


def demo_cancellation_mid_fanout(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    run_service = RunService(database)
    run = _create_run(
        run_service,
        alice,
        objective=DEPLOYMENT_AND_CUSTOMER_OBJECTIVE,
        strategy_kind="multi_agent_parallel",
        key=f"demo-multi-cancel-{uuid4()}",
    )
    cancelled = run_service.cancel(alice, run["id"], "Cancel mid-fan-out before any worker tick.")
    tasks = run_service.list_tasks(alice, run["id"])
    _print(
        "multi_agent_cancellation_propagates_mid_fanout",
        {
            "run_status": cancelled["status"],
            "task_statuses": {t["step_key"]: t["status"] for t in tasks},
        },
    )


def demo_strategy_comparison(database: Database, settings: Settings, alice: ActorContext) -> None:
    service = MultiAgentComparisonService(database, settings)
    result = service.run_comparison(alice, WORKSPACE_ID, f"demo-comparison-{uuid4()}")
    comparison = result["strategy_comparison"]
    _print(
        "multi_agent_vs_single_agent_comparison",
        {
            "objective": comparison["objective"],
            "single_agentic": comparison["metrics"]["single_agentic"],
            "multi_agent_parallel": comparison["metrics"]["multi_agent_parallel"],
            "caveats": comparison["caveats"],
            "paid_provider_calls": 0,
        },
    )


def demo_forged_role_denied(database: Database, alice: ActorContext) -> None:
    from forge_api.application.multi_agent_router import apply_router

    workflow_version = {
        "steps": [
            {
                "key": "spec_a",
                "name": "A",
                "kind": "agent",
                "input": {"agent_role": "deployment_specialist"},
            },
            {
                "key": "spec_forged",
                "name": "Forged",
                "kind": "agent",
                "input": {"agent_role": "root_admin_specialist"},
            },
        ],
        "edges": [],
    }
    try:
        apply_router(workflow_version=workflow_version, objective="deploy")
    except ProblemError as exc:
        _print(
            "multi_agent_forged_role_denied",
            {"code": exc.code, "status_code": exc.status_code},
        )
    else:
        raise RuntimeError("A forged/unknown specialist role was not denied.")


def main() -> None:
    settings = Settings()
    settings.assert_zero_cost_safe()
    _assert_local_url(settings.database_url, label="FORGE_DATABASE_URL")
    _assert_local_url(settings.migration_database_url, label="FORGE_MIGRATION_DATABASE_URL")
    _assert_local_url(settings.redis_url, label="FORGE_REDIS_URL")
    seed_main()
    _clear_queue(settings)
    database = Database(settings.database_url)
    alice = _actor(database, settings, "alice", Role.TENANT_ADMIN)
    ava = _actor(database, settings, "ava", Role.APPROVER)

    demo_router_fans_out_and_synthesizes(database, settings, alice, ava)
    demo_fallback_selects_all_specialists(database, settings, alice)
    demo_approval_gated_specialist(database, settings, alice, ava)
    demo_partial_and_total_failure(database, settings, alice)
    demo_cancellation_mid_fanout(database, settings, alice)
    demo_forged_role_denied(database, alice)
    demo_strategy_comparison(database, settings, alice)
    _print("phase12_zero_cost_summary", {"paid_provider_calls": 0, "live_model_calls": 0})


if __name__ == "__main__":
    main()
