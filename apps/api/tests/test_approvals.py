from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import pytest
from adversarial_cases import SSRF_DENIAL_CASES
from conftest import auth_headers
from fastapi.testclient import TestClient

from forge_api.api.errors import ProblemError
from forge_api.application.reliability_service import OutboxDispatcher, RetryPolicy, WorkerConsumer
from forge_api.config import Settings
from forge_api.domain.approvals import FakeSecretResolver, NetworkPolicy
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


def create_tool_run(client: TestClient, issuer: DevIssuer) -> Mapping[str, Any]:
    workflow = workflow_by_name(client, issuer, "Typed Tool Demo")
    response = client.post(
        "/v1/runs",
        headers=headers(issuer, key=f"phase6-run-{uuid4()}"),
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Exercise Phase 6 exact-action approval.",
        },
    )
    assert response.status_code == 201
    return response.json()["run"]


def worker_cycle(
    *,
    database: Database,
    settings: Settings,
    queue: InMemoryQueue,
) -> str:
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    consumer = WorkerConsumer(
        database=database,
        queue=queue,
        worker_id=settings.worker_id,
        lease_seconds=settings.task_lease_seconds,
        retry_policy=RetryPolicy(max_attempts=settings.task_max_attempts),
    )
    dispatcher.dispatch_once()
    return consumer.consume_once(block_ms=0)


def drive_until_waiting_approval(
    *,
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
    run_id: str,
) -> dict[str, Any]:
    queue = InMemoryQueue()
    for _ in range(20):
        worker_cycle(database=database, settings=settings, queue=queue)
        approvals = client.get("/v1/approvals", headers=headers(issuer, "ava")).json()[
            "approval_requests"
        ]
        pending = [
            approval
            for approval in approvals
            if approval["run_id"] == run_id and approval["status"] == "pending"
        ]
        if pending:
            return pending[0]
    raise AssertionError("run did not request approval")


def approve(
    client: TestClient,
    issuer: DevIssuer,
    approval: Mapping[str, Any],
    *,
    subject: str = "ava",
    key: str | None = None,
) -> TestClient:
    return client.post(
        f"/v1/approvals/{approval['id']}:approve",
        headers=headers(issuer, subject, key or f"approve-{uuid4()}")
        | {"If-Match": str(approval["request_version"])},
        json={"reason": "Approve exact local simulated effect."},
    )


def run_until_terminal_with_approval(
    *,
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
    run_id: str,
) -> Mapping[str, Any]:
    queue = InMemoryQueue()
    for _ in range(80):
        outcome = worker_cycle(database=database, settings=settings, queue=queue)
        if outcome == "waiting_approval":
            approval = next(
                approval
                for approval in client.get(
                    "/v1/approvals",
                    headers=headers(issuer, "ava"),
                ).json()["approval_requests"]
                if approval["run_id"] == run_id and approval["status"] == "pending"
            )
            response = approve(client, issuer, approval)
            assert response.status_code == 200
        current = client.get(f"/v1/runs/{run_id}", headers=headers(issuer)).json()["run"]
        if current["status"] in {"succeeded", "failed", "cancelled"}:
            return current
    raise AssertionError("run did not become terminal")


def test_simulated_effect_waits_for_exact_approval_then_resumes(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    run = create_tool_run(client, issuer)
    approval = drive_until_waiting_approval(
        database=database,
        settings=settings,
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )

    tasks = client.get(f"/v1/runs/{run['id']}/tasks", headers=headers(issuer)).json()["tasks"]
    assert any(task["status"] == "waiting_approval" for task in tasks)
    assert approval["status"] == "pending"
    assert approval["risk"] == "simulated_effect"
    assert approval["action_summary"]["tool_name"] == "ticket.create_simulated"

    response = approve(client, issuer, approval)
    assert response.status_code == 200
    assert response.json()["approval_request"]["status"] == "approved"

    completed = run_until_terminal_with_approval(
        database=database,
        settings=settings,
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )
    assert completed["status"] == "succeeded"
    consumed = client.get("/v1/approvals", headers=headers(issuer, "ava")).json()[
        "approval_requests"
    ]
    assert any(
        item["id"] == approval["id"] and item["status"] == "consumed" for item in consumed
    )


@pytest.mark.security
def test_self_viewer_and_outsider_approval_are_denied(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    run = create_tool_run(client, issuer)
    approval = drive_until_waiting_approval(
        database=database,
        settings=settings,
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )

    self_approval = approve(client, issuer, approval, subject="alice")
    viewer_approval = approve(client, issuer, approval, subject="bob")
    outsider_list = client.get("/v1/approvals", headers=headers(issuer, "mallory"))

    assert self_approval.status_code == 403
    assert self_approval.json()["code"] == "approval_self_forbidden"
    assert viewer_approval.status_code == 403
    assert viewer_approval.json()["code"] == "approval_decision_forbidden"
    assert outsider_list.json()["approval_requests"] == []


@pytest.mark.security
def test_approval_binding_mutation_is_rejected(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    run = create_tool_run(client, issuer)
    approval = drive_until_waiting_approval(
        database=database,
        settings=settings,
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )
    with database.transaction(
        tenant_id=approval["tenant_id"],
        actor_id=approval["requester_id"],
    ) as conn:
        conn.execute(
            """
            update tool_invocations
            set input = jsonb_set(input, '{severity}', '"high"')
            where id = %s
            """,
            (approval["tool_invocation_id"],),
        )

    response = approve(client, issuer, approval)

    assert response.status_code == 409
    assert response.json()["code"] == "approval_binding_mismatch"


@pytest.mark.security
def test_stale_approval_version_and_duplicate_decision_are_safe(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    run = create_tool_run(client, issuer)
    approval = drive_until_waiting_approval(
        database=database,
        settings=settings,
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )
    first = approve(client, issuer, approval, key="same-approval-click")
    replay = approve(client, issuer, approval, key="same-approval-click")
    second = approve(client, issuer, approval, key="second-approval-click")

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json() == replay.json()
    assert second.status_code == 409
    assert second.json()["code"] in {"approval_version_conflict", "approval_not_pending"}


@pytest.mark.security
def test_expired_approval_fails_closed(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    run = create_tool_run(client, issuer)
    approval = drive_until_waiting_approval(
        database=database,
        settings=settings,
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )
    with database.transaction(worker_id=settings.worker_id) as conn:
        cursor = conn.execute(
            "update approval_requests set expires_at = now() - interval '1 second' where id = %s",
            (approval["id"],),
        )
        assert cursor.rowcount == 1

    response = approve(client, issuer, approval)

    assert response.status_code == 409
    assert response.json()["code"] == "approval_expired"
    current = client.get(f"/v1/runs/{run['id']}", headers=headers(issuer)).json()["run"]
    assert current["status"] == "failed"


@pytest.mark.security
def test_approval_tables_are_hidden_without_rls_scope(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    run = create_tool_run(client, issuer)
    drive_until_waiting_approval(
        database=database,
        settings=settings,
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )

    with database.transaction() as conn:
        approvals = conn.execute("select id from approval_requests").fetchall()
        decisions = conn.execute("select id from approval_decisions").fetchall()

    assert approvals == []
    assert decisions == []


@pytest.mark.security
def test_network_policy_denies_ssrf_targets() -> None:
    policy = NetworkPolicy()

    for case in SSRF_DENIAL_CASES:
        with pytest.raises(ProblemError) as exc_info:
            policy.validate_url(case.url)
        assert exc_info.value.code == case.expected_code

    assert policy.validate_url("https://example.com/callback") == "https://example.com/callback"


@pytest.mark.security
def test_fake_secret_resolver_never_returns_secret_material() -> None:
    result = FakeSecretResolver().resolve_reference("secretref://local/ticket-demo")

    assert result["reference"] == "secretref://local/ticket-demo"
    assert result["material"] == "[redacted]"
