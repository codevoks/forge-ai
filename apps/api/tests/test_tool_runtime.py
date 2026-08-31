from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from conftest import auth_headers
from fastapi.testclient import TestClient

from forge_api.application.reliability_service import OutboxDispatcher, RetryPolicy, WorkerConsumer
from forge_api.config import Settings
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.dev_issuer import DevIssuer
from forge_api.infrastructure.queue import InMemoryQueue


def headers(issuer: DevIssuer, subject: str = "alice", key: str | None = None) -> dict[str, str]:
    request_headers = auth_headers(issuer, subject)
    if key:
        request_headers["Idempotency-Key"] = key
    return request_headers


def workflow_by_name(client: TestClient, issuer: DevIssuer, name: str) -> Mapping[str, Any]:
    workflows = client.get("/v1/workflows", headers=headers(issuer)).json()["workflow_versions"]
    return next(workflow for workflow in workflows if workflow["name"] == name)


def create_run(
    client: TestClient,
    issuer: DevIssuer,
    workflow: Mapping[str, Any],
    *,
    key: str,
) -> Mapping[str, Any]:
    response = client.post(
        "/v1/runs",
        headers=headers(issuer, key=f"{key}-{uuid4()}"),
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Exercise Phase 4 typed tool runtime.",
        },
    )
    assert response.status_code == 201
    return response.json()["run"]


def run_worker_until_terminal(
    *,
    database: Database,
    settings: Settings,
    queue: InMemoryQueue,
    client: TestClient,
    issuer: DevIssuer,
    run_id: str,
    max_ticks: int = 80,
    auto_approve: bool = True,
) -> Mapping[str, Any]:
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
            approve_pending_requests(client, issuer)
        client.post("/v1/operations/recovery:scan", headers=headers(issuer))
        run = client.get(f"/v1/runs/{run_id}", headers=headers(issuer)).json()["run"]
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            return run
    raise AssertionError("run did not become terminal")


def approve_pending_requests(client: TestClient, issuer: DevIssuer) -> None:
    response = client.get("/v1/approvals", headers=headers(issuer, "ava"))
    assert response.status_code == 200
    for approval in response.json()["approval_requests"]:
        if approval["status"] != "pending":
            continue
        approved = client.post(
            f"/v1/approvals/{approval['id']}:approve",
            headers=headers(issuer, "ava", f"approve-{approval['id']}-{uuid4()}")
            | {"If-Match": str(approval["request_version"])},
            json={"reason": "Ava approves the exact local simulated action."},
        )
        assert approved.status_code == 200


def publish_tool_workflow(
    client: TestClient,
    issuer: DevIssuer,
    *,
    key: str,
    name: str,
    step_input: dict[str, Any],
) -> Mapping[str, Any]:
    base = workflow_by_name(client, issuer, "Incident Response Demo")
    response = client.post(
        "/v1/workflows",
        headers=headers(issuer, key=key),
        json={
            "workspace_id": base["workspace_id"],
            "name": name,
            "steps": [
                {
                    "key": "tool_step",
                    "name": "Tool Step",
                    "kind": "tool",
                    "input": step_input,
                }
            ],
            "edges": [],
        },
    )
    assert response.status_code == 201
    return response.json()["workflow_version"]


def test_tool_catalog_lists_code_registered_versions(client: TestClient, issuer: DevIssuer) -> None:
    response = client.get("/v1/tools", headers=headers(issuer))

    assert response.status_code == 200
    tools = response.json()["tools"]
    assert {tool["name"] for tool in tools} >= {
        "deployment_history.lookup",
        "customer_reports.search",
        "ticket.create_simulated",
    }
    assert all(tool["status"] == "active" for tool in tools)


def test_tool_workflow_executes_with_intent_ledger_and_evidence(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    workflow = workflow_by_name(client, issuer, "Typed Tool Demo")
    run = create_run(client, issuer, workflow, key="phase4-tool-demo-run")

    completed = run_worker_until_terminal(
        database=database,
        settings=settings,
        queue=InMemoryQueue(),
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )

    assert completed["status"] == "succeeded"
    invocations = client.get(
        f"/v1/tools/runs/{run['id']}/invocations",
        headers=headers(issuer),
    ).json()["tool_invocations"]
    evidence = client.get(
        f"/v1/tools/runs/{run['id']}/evidence",
        headers=headers(issuer),
    ).json()["evidence_items"]
    assert {invocation["status"] for invocation in invocations} == {"succeeded"}
    assert {invocation["tool_name"] for invocation in invocations} == {
        "deployment_history.lookup",
        "customer_reports.search",
        "ticket.create_simulated",
    }
    assert len({invocation["action_hash"] for invocation in invocations}) == 3
    assert {item["trust_label"] for item in evidence} == {
        "trusted_local_fixture",
        "untrusted_tool_output",
    }


def test_tool_workflow_rejects_unknown_fields_before_adapter_execution(
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    base = workflow_by_name(client, issuer, "Incident Response Demo")
    response = client.post(
        "/v1/workflows",
        headers=headers(issuer, key="phase4-invalid-tool-schema"),
        json={
            "workspace_id": base["workspace_id"],
            "name": "Invalid Tool Schema Demo",
            "steps": [
                {
                    "key": "bad_tool",
                    "name": "Bad Tool",
                    "kind": "tool",
                    "input": {
                        "tool_name": "deployment_history.lookup",
                        "tool_version": 1,
                        "arguments": {
                            "service": "api",
                            "environment": "production",
                            "unexpected": "deny",
                        },
                    },
                }
            ],
            "edges": [],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "tool_input_invalid"


def test_ungranted_tool_task_fails_safely_without_adapter_execution(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    workflow = publish_tool_workflow(
        client,
        issuer,
        key="phase4-ungranted-workflow",
        name="Ungranted Tool Demo",
        step_input={
            "tool_name": "deployment_history.lookup",
            "tool_version": 1,
            "arguments": {"service": "api", "environment": "production"},
        },
    )
    run = create_run(client, issuer, workflow, key="phase4-ungranted-run")
    with database.transaction(worker_id=settings.worker_id) as conn:
        conn.execute("delete from run_tool_grants where run_id = %s", (run["id"],))

    completed = run_worker_until_terminal(
        database=database,
        settings=settings,
        queue=InMemoryQueue(),
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )

    assert completed["status"] == "failed"
    invocations = client.get(
        f"/v1/tools/runs/{run['id']}/invocations",
        headers=headers(issuer),
    ).json()["tool_invocations"]
    assert invocations == []


def test_duplicate_tool_invocation_reuses_logical_action(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    workflow = workflow_by_name(client, issuer, "Typed Tool Demo")
    run = create_run(client, issuer, workflow, key="phase4-duplicate-tool-run")
    queue = InMemoryQueue()
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    dispatcher.dispatch_once()
    queue.messages.extend(list(queue.messages))

    completed = run_worker_until_terminal(
        database=database,
        settings=settings,
        queue=queue,
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )

    assert completed["status"] == "succeeded"
    invocations = client.get(
        f"/v1/tools/runs/{run['id']}/invocations",
        headers=headers(issuer),
    ).json()["tool_invocations"]
    assert len(invocations) == 3


def test_simulated_effect_outcome_unknown_is_visible_in_invocation_ledger(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    workflow = publish_tool_workflow(
        client,
        issuer,
        key="phase4-outcome-unknown-workflow",
        name="Outcome Unknown Tool Demo",
        step_input={
            "tool_name": "ticket.create_simulated",
            "tool_version": 1,
            "arguments": {
                "title": "Ambiguous local ticket",
                "severity": "medium",
                "dry_run": True,
                "simulate_outcome_unknown": True,
            },
        },
    )
    run = create_run(client, issuer, workflow, key="phase4-outcome-unknown-run")

    completed = run_worker_until_terminal(
        database=database,
        settings=settings,
        queue=InMemoryQueue(),
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )

    assert completed["status"] == "failed"
    invocations = client.get(
        f"/v1/tools/runs/{run['id']}/invocations",
        headers=headers(issuer),
    ).json()["tool_invocations"]
    assert invocations[0]["status"] == "outcome_unknown"
    assert invocations[0]["error_type"] == "outcome_unknown"
