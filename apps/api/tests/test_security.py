from datetime import UTC, datetime, timedelta

import jwt
import pytest
from conftest import auth_headers
from fastapi.testclient import TestClient

from forge_api.config import Settings
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.dev_issuer import DevIssuer

pytestmark = pytest.mark.security


def seeded_workflow(client: TestClient, issuer: DevIssuer, subject: str = "alice") -> dict:
    workflows = client.get("/v1/workflows", headers=auth_headers(issuer, subject)).json()[
        "workflow_versions"
    ]
    return next(workflow for workflow in workflows if workflow["name"] == "Incident Response Demo")


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
