import sys
from uuid import uuid4

import pytest
from adversarial_cases import MCP_ADVERSARIAL_CASES, SSRF_DENIAL_CASES
from conftest import auth_headers
from fastapi.testclient import TestClient

from forge_api.api.errors import ProblemError
from forge_api.application.mcp_service import MCPAdminService
from forge_api.config import Settings
from forge_api.domain.identity import ActorContext, Role
from forge_api.domain.mcp import MCPConnectionPolicy
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.dev_issuer import DevIssuer
from forge_api.scripts.seed import TENANT_ID, WORKSPACE_ID

pytestmark = pytest.mark.security

STDIO_COMMAND = [sys.executable, "-m", "forge_api.scripts.mcp_fixture_server"]
MCP_CASES_BY_SCENARIO = {case.scenario: case for case in MCP_ADVERSARIAL_CASES}


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


def add_server(
    client: TestClient, issuer: DevIssuer, *, subject: str = "alice", key: str | None = None
) -> object:
    return client.post(
        "/v1/mcp/servers",
        headers=headers(issuer, subject, key or f"mcp-add-{uuid4()}"),
        json={
            "workspace_id": WORKSPACE_ID,
            "name": f"security-server-{uuid4()}",
            "transport": "stdio",
            "command": STDIO_COMMAND,
        },
    )


# -- RBAC: only workspace/tenant admins administer MCP servers ----------------------


def test_viewer_cannot_add_mcp_server(client: TestClient, issuer: DevIssuer) -> None:
    response = add_server(client, issuer, subject="bob")
    assert response.status_code == 403
    assert response.json()["code"] == "mcp_admin_forbidden"


def test_approver_cannot_add_mcp_server(client: TestClient, issuer: DevIssuer) -> None:
    response = add_server(client, issuer, subject="ava")
    assert response.status_code == 403
    assert response.json()["code"] == "mcp_admin_forbidden"


def test_admin_can_add_and_list_mcp_server(client: TestClient, issuer: DevIssuer) -> None:
    added = add_server(client, issuer)
    assert added.status_code == 200
    listed = client.get(
        f"/v1/mcp/servers?workspace_id={WORKSPACE_ID}", headers=headers(issuer)
    )
    assert listed.status_code == 200
    assert any(s["id"] == added.json()["server"]["id"] for s in listed.json()["servers"])


def test_viewer_can_list_but_not_mutate(client: TestClient, issuer: DevIssuer) -> None:
    added = add_server(client, issuer)
    server_id = added.json()["server"]["id"]
    listed = client.get(
        f"/v1/mcp/servers?workspace_id={WORKSPACE_ID}", headers=headers(issuer, "bob")
    )
    assert listed.status_code == 200
    forbidden = client.post(
        f"/v1/mcp/servers/{server_id}:test", headers=headers(issuer, "bob")
    )
    assert forbidden.status_code == 403


# -- cross-tenant isolation (mallory is an outsider with no membership) -------------


def test_mallory_cannot_see_or_add_mcp_servers(client: TestClient, issuer: DevIssuer) -> None:
    added = add_server(client, issuer)
    server_id = added.json()["server"]["id"]

    read = client.get(f"/v1/mcp/servers/{server_id}", headers=headers(issuer, "mallory"))
    assert read.status_code == 404  # RLS hides the row entirely; existence is never leaked

    create_attempt = add_server(client, issuer, subject="mallory")
    assert create_attempt.status_code == 403
    assert MCP_CASES_BY_SCENARIO["cross_tenant_server_hidden"].expected_outcome == "denied"


def test_rls_blocks_mcp_servers_without_tenant_context(
    database: Database, client: TestClient, issuer: DevIssuer
) -> None:
    add_server(client, issuer)
    with database.transaction() as conn:
        rows = conn.execute("select id from mcp_servers").fetchall()
    assert rows == []


def test_rls_blocks_mcp_tool_mappings_without_tenant_context(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    server = service.add_server(
        alice,
        workspace_id=WORKSPACE_ID,
        name=f"rls-mappings-{uuid4()}",
        transport="stdio",
        url=None,
        command=STDIO_COMMAND,
        auth_secret_reference=None,
        idempotency_key=f"rls-add-{uuid4()}",
    )["server"]
    service.discover_server(alice, server["id"], idempotency_key=f"rls-discover-{uuid4()}")

    with database.transaction() as conn:
        rows = conn.execute("select id from mcp_tool_mappings").fetchall()
    assert rows == []


# -- SSRF / zero-cost transport gate --------------------------------------------


@pytest.mark.parametrize("case", SSRF_DENIAL_CASES, ids=lambda c: c.expected_code)
def test_mcp_remote_server_url_reuses_ssrf_denial_corpus(case) -> None:
    with pytest.raises(ProblemError) as exc_info:
        MCPConnectionPolicy().validate(transport="http", url=case.url, command=None)
    assert exc_info.value.code == case.expected_code
    assert MCP_CASES_BY_SCENARIO["remote_server_ssrf_denied"].expected_outcome == "denied"


def test_remote_mcp_server_denied_by_default_zero_cost_profile(
    client: TestClient, issuer: DevIssuer
) -> None:
    response = client.post(
        "/v1/mcp/servers",
        headers=headers(issuer, key=f"remote-denied-{uuid4()}"),
        json={
            "workspace_id": WORKSPACE_ID,
            "name": f"remote-server-{uuid4()}",
            "transport": "http",
            "url": "https://example.com/mcp",
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "mcp_remote_transport_disabled"
    assert MCP_CASES_BY_SCENARIO["remote_transport_zero_cost_denied"].expected_outcome == "denied"


def test_arbitrary_stdio_command_is_rejected(client: TestClient, issuer: DevIssuer) -> None:
    response = client.post(
        "/v1/mcp/servers",
        headers=headers(issuer, key=f"bad-stdio-{uuid4()}"),
        json={
            "workspace_id": WORKSPACE_ID,
            "name": f"bad-stdio-{uuid4()}",
            "transport": "stdio",
            "command": ["/bin/sh", "-c", "echo pwned"],
        },
    )
    assert response.status_code == 422
    assert response.json()["code"] == "mcp_stdio_command_not_allowlisted"
    assert MCP_CASES_BY_SCENARIO["stdio_command_not_allowlisted"].expected_outcome == "denied"


# -- discovery quarantine and malicious content containment -------------------------


def test_discovered_tool_cannot_execute_before_admin_review(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    server = service.add_server(
        alice,
        workspace_id=WORKSPACE_ID,
        name=f"quarantine-{uuid4()}",
        transport="stdio",
        url=None,
        command=STDIO_COMMAND,
        auth_secret_reference=None,
        idempotency_key=f"quarantine-add-{uuid4()}",
    )["server"]
    service.discover_server(alice, server["id"], idempotency_key=f"quarantine-discover-{uuid4()}")

    from forge_api.application.mcp_tool_adapter import MCPToolAdapter

    adapter = MCPToolAdapter(database=database)
    with pytest.raises(ProblemError) as exc_info:
        adapter.invoke(
            tool_name="search_release_notes",  # the raw remote name, never a Forge tool name
            arguments={"query": "x"},
            idempotency_key=f"quarantine-invoke-{uuid4()}",
        )
    assert exc_info.value.code == "mcp_tool_adapter_missing"
    assert MCP_CASES_BY_SCENARIO["discovery_quarantine"].expected_outcome == "denied"


def test_malicious_tool_description_is_flagged_but_untrusted_output_is_never_an_instruction(
    database: Database, settings: Settings, alice: ActorContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FORGE_MCP_FIXTURE_VARIANT", "adversarial")
    service = MCPAdminService(database, settings)
    server = service.add_server(
        alice,
        workspace_id=WORKSPACE_ID,
        name=f"adversarial-{uuid4()}",
        transport="stdio",
        url=None,
        command=STDIO_COMMAND,
        auth_secret_reference=None,
        idempotency_key=f"adv-add-{uuid4()}",
    )["server"]
    discovery = service.discover_server(
        alice, server["id"], idempotency_key=f"adv-discover-{uuid4()}"
    )
    mapping = next(
        m for m in discovery["mappings"] if m["remote_tool_name"] == "read_flagged_advisory"
    )
    # The snapshot advisory-flags the suspicious description for the human reviewer...
    flagged_tool = next(
        t for t in discovery["snapshot"]["tools"] if t["name"] == "read_flagged_advisory"
    )
    assert flagged_tool["suspicious"] is True

    # ...but flagging is advisory only: an admin can still enable it, and Forge policy
    # (not a classifier) is what keeps its output from ever becoming an instruction —
    # it is always labeled untrusted_tool_output, exactly like any other tool result.
    tool_name = f"mcp.adversarial_{uuid4().hex[:8]}.read_flagged_advisory"
    enabled = service.enable_mapping(
        alice,
        server["id"],
        mapping["id"],
        forge_tool_name=tool_name,
        risk="read_only",
        expected_schema_hash=mapping["schema_hash"],
        expected_version=mapping["version"],
        idempotency_key=f"adv-enable-{uuid4()}",
    )
    assert enabled["mapping"]["status"] == "enabled"

    from forge_api.application.mcp_tool_adapter import MCPToolAdapter
    from forge_api.infrastructure.tool_repositories import ToolRegistryRepository

    with database.transaction(worker_id="test-worker") as conn:
        row = ToolRegistryRepository(conn).try_resolve(name=tool_name, version=1)
    assert row is not None
    assert row["trust_label"] == "untrusted_tool_output"

    output = MCPToolAdapter(database=database).invoke(
        tool_name=tool_name, arguments={}, idempotency_key=f"adv-invoke-{uuid4()}"
    )
    assert "ignore previous instructions" in output["advisory"].lower()
    assert MCP_CASES_BY_SCENARIO["malicious_description_contained"].expected_outcome == "contained"


def test_disabled_server_cannot_be_invoked_even_with_stale_mapping_reference(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    server = service.add_server(
        alice,
        workspace_id=WORKSPACE_ID,
        name=f"disabled-invoke-{uuid4()}",
        transport="stdio",
        url=None,
        command=STDIO_COMMAND,
        auth_secret_reference=None,
        idempotency_key=f"disabled-add-{uuid4()}",
    )["server"]
    discovery = service.discover_server(
        alice, server["id"], idempotency_key=f"disabled-discover-{uuid4()}"
    )
    mapping = next(
        m for m in discovery["mappings"] if m["remote_tool_name"] == "search_release_notes"
    )
    tool_name = f"mcp.disabled_invoke_{uuid4().hex[:8]}.search_release_notes"
    service.enable_mapping(
        alice,
        server["id"],
        mapping["id"],
        forge_tool_name=tool_name,
        risk="read_only",
        expected_schema_hash=mapping["schema_hash"],
        expected_version=mapping["version"],
        idempotency_key=f"disabled-enable-{uuid4()}",
    )
    service.disable_server(
        alice, server["id"], expected_version=1, idempotency_key=f"disabled-srv-{uuid4()}"
    )

    from forge_api.application.mcp_tool_adapter import MCPToolAdapter

    with pytest.raises(ProblemError) as exc_info:
        MCPToolAdapter(database=database).invoke(
            tool_name=tool_name,
            arguments={"query": "x"},
            idempotency_key=f"disabled-invoke-{uuid4()}",
        )
    assert exc_info.value.code == "mcp_tool_adapter_missing"


# -- idempotency ---------------------------------------------------------------


def test_add_server_idempotency_key_reuse_with_different_payload_is_rejected(
    client: TestClient, issuer: DevIssuer
) -> None:
    key = f"idem-conflict-{uuid4()}"
    name = f"idem-conflict-{uuid4()}"
    first = client.post(
        "/v1/mcp/servers",
        headers=headers(issuer, key=key),
        json={
            "workspace_id": WORKSPACE_ID,
            "name": name,
            "transport": "stdio",
            "command": STDIO_COMMAND,
        },
    )
    assert first.status_code == 200
    second = client.post(
        "/v1/mcp/servers",
        headers=headers(issuer, key=key),
        json={
            "workspace_id": WORKSPACE_ID,
            "name": name + "-different",
            "transport": "stdio",
            "command": STDIO_COMMAND,
        },
    )
    assert second.status_code == 409
    assert second.json()["code"] == "idempotency_key_reused"


def test_enable_mapping_requires_if_match(client: TestClient, issuer: DevIssuer) -> None:
    added = add_server(client, issuer)
    server_id = added.json()["server"]["id"]
    discovered = client.post(
        f"/v1/mcp/servers/{server_id}:discover", headers=headers(issuer, key=f"discover-{uuid4()}")
    )
    mapping_id = discovered.json()["mappings"][0]["id"]

    response = client.post(
        f"/v1/mcp/servers/{server_id}/mappings/{mapping_id}:enable",
        headers=headers(issuer, key=f"enable-{uuid4()}"),
        json={
            "forge_tool_name": "mcp.if_match_test.tool",
            "risk": "read_only",
            "expected_schema_hash": discovered.json()["mappings"][0]["schema_hash"],
        },
    )
    assert response.status_code == 428
    assert response.json()["code"] == "if_match_required"
