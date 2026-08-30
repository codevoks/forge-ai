from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from conftest import auth_headers
from fastapi.testclient import TestClient

from forge_api.application.reliability_service import OutboxDispatcher, RetryPolicy, WorkerConsumer
from forge_api.config import Settings
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.dev_issuer import DevIssuer
from forge_api.infrastructure.queue import InMemoryQueue

pytestmark = pytest.mark.security


def seeded_workflow(client: TestClient, issuer: DevIssuer, subject: str = "alice") -> dict:
    workflows = client.get("/v1/workflows", headers=auth_headers(issuer, subject)).json()[
        "workflow_versions"
    ]
    return next(workflow for workflow in workflows if workflow["name"] == "Incident Response Demo")


def seeded_tool_workflow(client: TestClient, issuer: DevIssuer, subject: str = "alice") -> dict:
    workflows = client.get("/v1/workflows", headers=auth_headers(issuer, subject)).json()[
        "workflow_versions"
    ]
    return next(workflow for workflow in workflows if workflow["name"] == "Typed Tool Demo")


def create_and_complete_tool_run(
    *,
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
) -> dict:
    workflow = seeded_tool_workflow(client, issuer)
    run = client.post(
        "/v1/runs",
        headers=auth_headers(issuer, "alice") | {"Idempotency-Key": f"security-tool-run-{uuid4()}"},
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Create tool evidence for security inspection.",
        },
    ).json()["run"]
    queue = InMemoryQueue()
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    consumer = WorkerConsumer(
        database=database,
        queue=queue,
        worker_id=settings.worker_id,
        lease_seconds=settings.task_lease_seconds,
        retry_policy=RetryPolicy(max_attempts=settings.task_max_attempts),
    )
    for _ in range(80):
        dispatcher.dispatch_once()
        consumer.consume_once(block_ms=0)
        current = client.get(f"/v1/runs/{run['id']}", headers=auth_headers(issuer, "alice")).json()[
            "run"
        ]
        if current["status"] == "succeeded":
            return current
    raise AssertionError("tool run did not complete")


def test_unsigned_jwt_is_rejected(client: TestClient, settings: Settings) -> None:
    now = datetime.now(tz=UTC)
    token = jwt.encode(
        {
            "iss": settings.oidc_issuer,
            "aud": settings.oidc_audience,
            "sub": "oidc|attacker",
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        key="",
        algorithm="none",
    )

    response = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_token_algorithm"


def test_wrong_audience_token_is_rejected(client: TestClient, issuer: DevIssuer) -> None:
    token = issuer.token_for_subject(
        subject="oidc|alice",
        email="alice@forge.local",
        name="Alice Admin",
        overrides={"aud": "other-audience"},
    )

    response = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_token"


def test_expired_token_is_rejected(client: TestClient, issuer: DevIssuer) -> None:
    token = issuer.token_for_subject(
        subject="oidc|alice",
        email="alice@forge.local",
        name="Alice Admin",
        ttl_seconds=-60,
    )

    response = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["code"] == "token_expired"


def test_cross_tenant_workspace_idor_is_denied(client: TestClient, issuer: DevIssuer) -> None:
    alice = client.get("/v1/me", headers=auth_headers(issuer, "alice")).json()
    workspace_id = alice["workspaces"][0]["id"]

    response = client.get(f"/v1/workspaces/{workspace_id}", headers=auth_headers(issuer, "mallory"))

    assert response.status_code == 403
    assert response.json()["code"] == "workspace_forbidden"


def test_rls_blocks_rows_without_transaction_tenant_context(database: Database) -> None:
    with database.transaction() as conn:
        rows = conn.execute("select id from workspaces").fetchall()

    assert rows == []


def test_rls_allows_only_configured_tenant(database: Database) -> None:
    tenant_id = "018f0000-0000-7000-8000-000000000001"
    with database.transaction(tenant_id=tenant_id) as conn:
        rows = conn.execute("select tenant_id from workspaces").fetchall()

    assert rows
    assert {str(row["tenant_id"]) for row in rows} == {tenant_id}


def test_auth_endpoint_rate_limit_fails_closed(client: TestClient) -> None:
    last_status = 200
    for _ in range(31):
        last_status = client.get("/dev/oidc/token/alice").status_code

    assert last_status == 429


def test_viewer_cannot_publish_workflow(client: TestClient, issuer: DevIssuer) -> None:
    workspace = client.get("/v1/me", headers=auth_headers(issuer, "bob")).json()["workspaces"][0]

    response = client.post(
        "/v1/workflows",
        headers=auth_headers(issuer, "bob") | {"Idempotency-Key": "viewer-workflow-publish"},
        json={
            "workspace_id": workspace["id"],
            "name": "Viewer Workflow",
            "steps": [{"key": "only", "name": "Only Step", "kind": "deterministic"}],
            "edges": [],
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "workflow_publish_forbidden"


def test_viewer_cannot_create_run(client: TestClient, issuer: DevIssuer) -> None:
    workflow = seeded_workflow(client, issuer, "bob")

    response = client.post(
        "/v1/runs",
        headers=auth_headers(issuer, "bob") | {"Idempotency-Key": "viewer-run-create"},
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Viewer should not create runs.",
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "run_create_forbidden"


def test_cross_tenant_run_idor_is_not_exposed(client: TestClient, issuer: DevIssuer) -> None:
    workflow = seeded_workflow(client, issuer)
    created = client.post(
        "/v1/runs",
        headers=auth_headers(issuer, "alice") | {"Idempotency-Key": "run-idor-source"},
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Create a run Mallory must not read.",
        },
    ).json()["run"]

    response = client.get(f"/v1/runs/{created['id']}", headers=auth_headers(issuer, "mallory"))

    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"


def test_runtime_role_cannot_mutate_published_workflow_snapshot(database: Database) -> None:
    tenant_id = "018f0000-0000-7000-8000-000000000001"

    with pytest.raises(Exception, match="published workflow versions are immutable"):
        with database.transaction(tenant_id=tenant_id) as conn:
            conn.execute(
                """
                update workflow_steps
                set name = 'Tampered'
                where workflow_version_id = '018f0000-0000-7000-8000-000000000202'
                """
            )


def test_phase2_rls_blocks_runs_without_scope(
    database: Database, client: TestClient, issuer: DevIssuer
) -> None:
    workflow = seeded_workflow(client, issuer)
    created = client.post(
        "/v1/runs",
        headers=auth_headers(issuer, "alice") | {"Idempotency-Key": "rls-run-source"},
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Create a run for RLS inspection.",
        },
    )
    assert created.status_code == 201

    with database.transaction() as conn:
        rows = conn.execute("select id from runs").fetchall()

    assert rows == []


def test_viewer_cannot_trigger_recovery_scan(client: TestClient, issuer: DevIssuer) -> None:
    response = client.post("/v1/operations/recovery:scan", headers=auth_headers(issuer, "bob"))

    assert response.status_code == 403
    assert response.json()["code"] == "recovery_forbidden"


def test_viewer_cannot_inspect_dead_letters(client: TestClient, issuer: DevIssuer) -> None:
    response = client.get("/v1/operations/dead-letters", headers=auth_headers(issuer, "bob"))

    assert response.status_code == 403
    assert response.json()["code"] == "recovery_forbidden"


def test_phase3_rls_blocks_outbox_without_scope(
    database: Database, client: TestClient, issuer: DevIssuer
) -> None:
    workflow = seeded_workflow(client, issuer)
    created = client.post(
        "/v1/runs",
        headers=auth_headers(issuer, "alice") | {"Idempotency-Key": "rls-outbox-source"},
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Create outbox rows for RLS inspection.",
        },
    )
    assert created.status_code == 201

    with database.transaction() as conn:
        rows = conn.execute("select id from outbox_messages").fetchall()

    assert rows == []


def test_tool_invocation_and_evidence_rls_block_without_scope(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    create_and_complete_tool_run(
        database=database,
        settings=settings,
        client=client,
        issuer=issuer,
    )

    with database.transaction() as conn:
        invocation_rows = conn.execute("select id from tool_invocations").fetchall()
        evidence_rows = conn.execute("select id from evidence_items").fetchall()

    assert invocation_rows == []
    assert evidence_rows == []


def test_mallory_cannot_read_tool_invocations_or_evidence(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    run = create_and_complete_tool_run(
        database=database,
        settings=settings,
        client=client,
        issuer=issuer,
    )

    invocations = client.get(
        f"/v1/tools/runs/{run['id']}/invocations",
        headers=auth_headers(issuer, "mallory"),
    )
    evidence = client.get(
        f"/v1/tools/runs/{run['id']}/evidence",
        headers=auth_headers(issuer, "mallory"),
    )

    assert invocations.status_code == 404
    assert evidence.status_code == 404


def test_untrusted_tool_output_is_labeled_not_executed_as_instruction(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    run = create_and_complete_tool_run(
        database=database,
        settings=settings,
        client=client,
        issuer=issuer,
    )

    evidence = client.get(
        f"/v1/tools/runs/{run['id']}/evidence",
        headers=auth_headers(issuer, "alice"),
    ).json()["evidence_items"]
    untrusted = next(item for item in evidence if item["trust_label"] == "untrusted_tool_output")

    assert "ignore previous instructions" in str(untrusted["summary"])
    assert untrusted["source_name"] == "customer_reports.search"
    assert run["status"] == "succeeded"
