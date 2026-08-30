from conftest import auth_headers
from fastapi.testclient import TestClient

from forge_api.infrastructure.dev_issuer import DevIssuer


def test_ready_reports_zero_cost_profile(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["external_integrations"] == "disabled"


def test_authenticated_user_sees_seeded_workspace(client: TestClient, issuer: DevIssuer) -> None:
    response = client.get("/v1/me", headers=auth_headers(issuer, "alice"))

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "alice@forge.local"
    seeded = [
        workspace
        for workspace in body["workspaces"]
        if workspace["name"] == "Security Demo Workspace"
    ]
    assert seeded
    assert seeded[0]["role"] == "tenant_admin"


def test_idempotent_tenant_create_replays_same_response(
    client: TestClient, issuer: DevIssuer
) -> None:
    headers = auth_headers(issuer, "alice") | {"Idempotency-Key": "tenant-create-stable"}
    payload = {"name": "Acme Demo", "workspace_name": "Acme Workspace"}

    first = client.post("/v1/tenants", json=payload, headers=headers)
    second = client.post("/v1/tenants", json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json() == second.json()


def test_idempotency_key_reuse_with_different_payload_fails(
    client: TestClient, issuer: DevIssuer
) -> None:
    headers = auth_headers(issuer, "alice") | {"Idempotency-Key": "tenant-create-conflict"}

    first = client.post("/v1/tenants", json={"name": "One"}, headers=headers)
    second = client.post("/v1/tenants", json={"name": "Two"}, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["code"] == "idempotency_key_reused"


def test_missing_idempotency_key_fails_closed(client: TestClient, issuer: DevIssuer) -> None:
    response = client.post(
        "/v1/tenants",
        json={"name": "Missing Key"},
        headers=auth_headers(issuer, "alice"),
    )

    assert response.status_code == 400
    assert response.json()["code"] == "idempotency_key_required"


def test_invalid_tenant_payload_is_rejected(client: TestClient, issuer: DevIssuer) -> None:
    response = client.post(
        "/v1/tenants",
        json={"name": "x"},
        headers=auth_headers(issuer, "alice") | {"Idempotency-Key": "invalid-payload"},
    )

    assert response.status_code == 422
