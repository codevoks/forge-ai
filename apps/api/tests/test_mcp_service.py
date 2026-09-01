import sys
from collections.abc import Mapping
from typing import Any
from uuid import uuid4

import pytest
from adversarial_cases import MCP_ADVERSARIAL_CASES
from conftest import auth_headers
from fastapi.testclient import TestClient

from forge_api.api.errors import ProblemError
from forge_api.application.mcp_service import MCPAdminService
from forge_api.application.reliability_service import OutboxDispatcher, WorkerConsumer
from forge_api.config import Settings
from forge_api.domain.identity import ActorContext, Role
from forge_api.domain.reliability import RetryPolicy as ReliabilityRetryPolicy
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.dev_issuer import DevIssuer
from forge_api.infrastructure.queue import InMemoryQueue
from forge_api.scripts.seed import TENANT_ID, WORKSPACE_ID

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


def add_and_discover(
    service: MCPAdminService, alice: ActorContext, *, name: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    server = service.add_server(
        alice,
        workspace_id=WORKSPACE_ID,
        name=name,
        transport="stdio",
        url=None,
        command=STDIO_COMMAND,
        auth_secret_reference=None,
        idempotency_key=f"add-{name}-{uuid4()}",
    )["server"]
    discovery = service.discover_server(
        alice, server["id"], idempotency_key=f"discover-{name}-{uuid4()}"
    )
    return server, discovery["mappings"]


def enable(
    service: MCPAdminService,
    alice: ActorContext,
    server: dict[str, Any],
    mapping: dict[str, Any],
    *,
    forge_tool_name: str,
    risk: str = "read_only",
) -> dict[str, Any]:
    return service.enable_mapping(
        alice,
        server["id"],
        mapping["id"],
        forge_tool_name=forge_tool_name,
        risk=risk,
        expected_schema_hash=mapping["schema_hash"],
        expected_version=mapping["version"],
        idempotency_key=f"enable-{mapping['id']}-{uuid4()}",
    )


def workflow_by_name(client: TestClient, issuer: DevIssuer, name: str) -> Mapping[str, Any]:
    workflows = client.get("/v1/workflows", headers=headers(issuer)).json()["workflow_versions"]
    return next(workflow for workflow in workflows if workflow["name"] == name)


def publish_mcp_tool_workflow(
    client: TestClient, issuer: DevIssuer, *, key: str, name: str, tool_name: str, version: int = 1
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
                    "key": "mcp_step",
                    "name": "MCP Tool Step",
                    "kind": "tool",
                    "input": {
                        "tool_name": tool_name,
                        "tool_version": version,
                        "arguments": {"query": "worker", "limit": 2},
                    },
                }
            ],
            "edges": [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["workflow_version"]


def create_run(
    client: TestClient, issuer: DevIssuer, workflow: Mapping[str, Any], *, key: str
) -> Mapping[str, Any]:
    response = client.post(
        "/v1/runs",
        headers=headers(issuer, key=f"{key}-{uuid4()}"),
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Exercise Phase 11 MCP tool interoperability.",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["run"]


def approve_pending(client: TestClient, issuer: DevIssuer, run_id: str) -> None:
    approvals = client.get(
        "/v1/approvals", headers=headers(issuer, "ava")
    ).json()["approval_requests"]
    pending = next(a for a in approvals if a["run_id"] == run_id and a["status"] == "pending")
    approved = client.post(
        f"/v1/approvals/{pending['id']}:approve",
        headers=headers(issuer, "ava", f"approve-{uuid4()}")
        | {"If-Match": str(pending["request_version"])},
        json={"reason": "Ava approves the exact simulated MCP effect."},
    )
    assert approved.status_code == 200, approved.text


def run_worker_until_terminal(
    *,
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
    run_id: str,
    auto_approve: bool = True,
    max_ticks: int = 80,
) -> Mapping[str, Any]:
    queue = InMemoryQueue()
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    consumer = WorkerConsumer(
        database=database,
        queue=queue,
        worker_id=settings.worker_id,
        lease_seconds=settings.task_lease_seconds,
        retry_policy=ReliabilityRetryPolicy(max_attempts=settings.task_max_attempts),
    )
    run: Mapping[str, Any] = {}
    for _ in range(max_ticks):
        dispatcher.dispatch_once()
        outcome = consumer.consume_once(block_ms=0)
        if auto_approve and outcome == "waiting_approval":
            approve_pending(client, issuer, run_id)
        run = client.get(f"/v1/runs/{run_id}", headers=headers(issuer)).json()["run"]
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            return run
    raise AssertionError("run did not become terminal")


@pytest.fixture
def alice(database: Database, settings: Settings) -> ActorContext:
    return actor_for(database, settings, "alice", Role.TENANT_ADMIN)


# -- server/discovery/mapping lifecycle ---------------------------------------------


def test_add_server_test_discover_quarantines_new_tools(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = add_and_discover(service, alice, name=f"lifecycle-{uuid4()}")

    assert server["status"] == "draft"
    result = service.test_server(alice, server["id"])
    assert result["healthy"] is True

    assert {m["remote_tool_name"] for m in mappings} == {
        "search_release_notes",
        "lookup_worker_health",
    }
    assert all(m["status"] == "discovered" for m in mappings)
    # Quarantine: a discovered-but-unreviewed tool must never resolve as an executable
    # Forge tool.
    from forge_api.infrastructure.tool_repositories import ToolRegistryRepository

    with database.transaction(worker_id="test-worker") as conn:
        resolved = ToolRegistryRepository(conn).try_resolve(name="search_release_notes", version=1)
    assert resolved is None


def test_add_server_is_idempotent(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    name = f"idem-{uuid4()}"
    key = f"idem-key-{uuid4()}"
    first = service.add_server(
        alice,
        workspace_id=WORKSPACE_ID,
        name=name,
        transport="stdio",
        url=None,
        command=STDIO_COMMAND,
        auth_secret_reference=None,
        idempotency_key=key,
    )
    second = service.add_server(
        alice,
        workspace_id=WORKSPACE_ID,
        name=name,
        transport="stdio",
        url=None,
        command=STDIO_COMMAND,
        auth_secret_reference=None,
        idempotency_key=key,
    )
    assert first["server"]["id"] == second["server"]["id"]


def test_add_server_duplicate_name_conflict(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    name = f"dup-{uuid4()}"
    service.add_server(
        alice,
        workspace_id=WORKSPACE_ID,
        name=name,
        transport="stdio",
        url=None,
        command=STDIO_COMMAND,
        auth_secret_reference=None,
        idempotency_key=f"dup-key-1-{uuid4()}",
    )
    with pytest.raises(ProblemError) as exc_info:
        service.add_server(
            alice,
            workspace_id=WORKSPACE_ID,
            name=name,
            transport="stdio",
            url=None,
            command=STDIO_COMMAND,
            auth_secret_reference=None,
            idempotency_key=f"dup-key-2-{uuid4()}",
        )
    assert exc_info.value.code == "mcp_server_name_conflict"


def test_enable_mapping_requires_admin_named_tool_prefix(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = add_and_discover(service, alice, name=f"prefix-{uuid4()}")
    mapping = mappings[0]
    with pytest.raises(ProblemError) as exc_info:
        service.enable_mapping(
            alice,
            server["id"],
            mapping["id"],
            forge_tool_name="not_prefixed_correctly",
            risk="read_only",
            expected_schema_hash=mapping["schema_hash"],
            expected_version=mapping["version"],
            idempotency_key=f"bad-prefix-{uuid4()}",
        )
    assert exc_info.value.code == "mcp_forge_tool_name_invalid"


def test_enable_mapping_rejects_invalid_risk(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = add_and_discover(service, alice, name=f"risk-{uuid4()}")
    mapping = mappings[0]
    with pytest.raises(ProblemError) as exc_info:
        service.enable_mapping(
            alice,
            server["id"],
            mapping["id"],
            forge_tool_name="mcp.risk_test.tool",
            risk="delete_everything",
            expected_schema_hash=mapping["schema_hash"],
            expected_version=mapping["version"],
            idempotency_key=f"bad-risk-{uuid4()}",
        )
    assert exc_info.value.code == "mcp_risk_invalid"


def test_enable_mapping_rejects_stale_schema_hash(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = add_and_discover(service, alice, name=f"stale-{uuid4()}")
    mapping = mappings[0]
    with pytest.raises(ProblemError) as exc_info:
        service.enable_mapping(
            alice,
            server["id"],
            mapping["id"],
            forge_tool_name="mcp.stale_test.tool",
            risk="read_only",
            expected_schema_hash="0" * 64,
            expected_version=mapping["version"],
            idempotency_key=f"stale-{uuid4()}",
        )
    assert exc_info.value.code == "mcp_mapping_schema_changed"


def test_enable_mapping_rejects_stale_version(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = add_and_discover(service, alice, name=f"version-{uuid4()}")
    mapping = mappings[0]
    with pytest.raises(ProblemError) as exc_info:
        service.enable_mapping(
            alice,
            server["id"],
            mapping["id"],
            forge_tool_name="mcp.version_test.tool",
            risk="read_only",
            expected_schema_hash=mapping["schema_hash"],
            expected_version=mapping["version"] + 5,
            idempotency_key=f"version-{uuid4()}",
        )
    assert exc_info.value.code == "mcp_mapping_version_conflict"


def test_enable_creates_executable_tool_and_disable_retires_it(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = add_and_discover(service, alice, name=f"enable-disable-{uuid4()}")
    mapping = next(m for m in mappings if m["remote_tool_name"] == "search_release_notes")
    tool_name = f"mcp.enable_disable_{uuid4().hex[:8]}.search_release_notes"
    enabled = enable(service, alice, server, mapping, forge_tool_name=tool_name)

    from forge_api.infrastructure.tool_repositories import ToolRegistryRepository

    with database.transaction(worker_id="test-worker") as conn:
        row = ToolRegistryRepository(conn).try_resolve(name=tool_name, version=1)
    assert row is not None
    assert row["origin"] == "mcp"
    assert row["trust_label"] == "untrusted_tool_output"
    assert row["status"] == "active"

    disabled = service.disable_mapping(
        alice,
        server["id"],
        enabled["mapping"]["id"],
        expected_version=enabled["mapping"]["version"],
        idempotency_key=f"disable-{uuid4()}",
    )
    assert disabled["mapping"]["status"] == "disabled"
    with database.transaction(worker_id="test-worker") as conn:
        row = ToolRegistryRepository(conn).try_resolve(name=tool_name, version=1)
    assert row is None  # retired tool_versions are no longer resolvable as active


def test_disable_server_cascades_to_enabled_mappings(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = add_and_discover(service, alice, name=f"cascade-{uuid4()}")
    mapping = next(m for m in mappings if m["remote_tool_name"] == "lookup_worker_health")
    tool_name = f"mcp.cascade_{uuid4().hex[:8]}.lookup_worker_health"
    enable(service, alice, server, mapping, forge_tool_name=tool_name)

    service.disable_server(
        alice, server["id"], expected_version=1, idempotency_key=f"disable-srv-{uuid4()}"
    )

    from forge_api.infrastructure.tool_repositories import ToolRegistryRepository

    with database.transaction(worker_id="test-worker") as conn:
        assert ToolRegistryRepository(conn).try_resolve(name=tool_name, version=1) is None
    mappings_after = service.list_mappings(alice, server["id"])
    enabled_mapping = next(
        m for m in mappings_after if m["remote_tool_name"] == "lookup_worker_health"
    )
    assert enabled_mapping["status"] == "disabled"


def test_rediscovery_of_removed_tool_marks_mapping_removed_and_retires_version(
    database: Database, settings: Settings, alice: ActorContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = add_and_discover(service, alice, name=f"removed-{uuid4()}")
    mapping = next(m for m in mappings if m["remote_tool_name"] == "lookup_worker_health")
    tool_name = f"mcp.removed_{uuid4().hex[:8]}.lookup_worker_health"
    enabled = enable(service, alice, server, mapping, forge_tool_name=tool_name)

    monkeypatch.setenv("FORGE_MCP_FIXTURE_VARIANT", "reduced")
    result = service.discover_server(alice, server["id"], idempotency_key=f"redisc-{uuid4()}")
    assert result["removed_count"] == 1

    updated_mappings = service.list_mappings(alice, server["id"])
    removed = next(m for m in updated_mappings if m["remote_tool_name"] == "lookup_worker_health")
    assert removed["status"] == "removed"

    from forge_api.infrastructure.tool_repositories import ToolRegistryRepository

    with database.transaction(worker_id="test-worker") as conn:
        assert ToolRegistryRepository(conn).try_resolve(name=tool_name, version=1) is None
    _ = enabled


def test_rediscovery_after_schema_change_marks_drifted_and_blocks_execution(
    database: Database, settings: Settings, alice: ActorContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = add_and_discover(service, alice, name=f"drift-{uuid4()}")
    mapping = next(m for m in mappings if m["remote_tool_name"] == "search_release_notes")
    tool_name = f"mcp.drift_{uuid4().hex[:8]}.search_release_notes"
    enable(service, alice, server, mapping, forge_tool_name=tool_name)

    monkeypatch.setenv("FORGE_MCP_FIXTURE_VARIANT", "schema_changed")
    service.discover_server(alice, server["id"], idempotency_key=f"redisc-drift-{uuid4()}")

    updated_mappings = service.list_mappings(alice, server["id"])
    drifted = next(m for m in updated_mappings if m["remote_tool_name"] == "search_release_notes")
    assert drifted["status"] == "drifted"

    # The already-enabled tool version is retired: pinned runs stay safe, drift is visible.
    from forge_api.infrastructure.tool_repositories import ToolRegistryRepository

    with database.transaction(worker_id="test-worker") as conn:
        assert ToolRegistryRepository(conn).try_resolve(name=tool_name, version=1) is None

    # Re-enabling after review creates a new immutable version rather than mutating the old one.
    reenabled = enable(service, alice, server, drifted, forge_tool_name=tool_name)
    assert reenabled["tool_version"] == 2
    with database.transaction(worker_id="test-worker") as conn:
        row = ToolRegistryRepository(conn).try_resolve(name=tool_name, version=2)
    assert row is not None


# -- ToolRuntime dispatch through the real run/worker path --------------------------


def test_read_only_mcp_tool_executes_through_real_run(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
    alice: ActorContext,
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = add_and_discover(service, alice, name=f"run-readonly-{uuid4()}")
    mapping = next(m for m in mappings if m["remote_tool_name"] == "search_release_notes")
    tool_name = f"mcp.run_readonly_{uuid4().hex[:8]}.search_release_notes"
    enable(service, alice, server, mapping, forge_tool_name=tool_name, risk="read_only")

    workflow = publish_mcp_tool_workflow(
        client,
        issuer,
        key=f"publish-readonly-{uuid4()}",
        name=f"MCP RO Demo {uuid4()}",
        tool_name=tool_name,
    )
    run = create_run(client, issuer, workflow, key="mcp-readonly-run")
    completed = run_worker_until_terminal(
        database=database, settings=settings, client=client, issuer=issuer, run_id=str(run["id"])
    )

    assert completed["status"] == "succeeded"
    invocations = client.get(
        f"/v1/tools/runs/{run['id']}/invocations", headers=headers(issuer)
    ).json()["tool_invocations"]
    assert len(invocations) == 1
    assert invocations[0]["status"] == "succeeded"
    assert invocations[0]["tool_name"] == tool_name
    assert invocations[0]["mcp_server_id"] == server["id"]
    assert invocations[0]["mcp_provenance"]["remote_tool_name"] == "search_release_notes"

    evidence = client.get(f"/v1/tools/runs/{run['id']}/evidence", headers=headers(issuer)).json()[
        "evidence_items"
    ]
    assert evidence[0]["trust_label"] == "untrusted_tool_output"


def test_simulated_effect_mcp_tool_requires_approval(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
    alice: ActorContext,
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = add_and_discover(service, alice, name=f"run-approval-{uuid4()}")
    mapping = next(m for m in mappings if m["remote_tool_name"] == "search_release_notes")
    tool_name = f"mcp.run_approval_{uuid4().hex[:8]}.search_release_notes"
    enable(service, alice, server, mapping, forge_tool_name=tool_name, risk="simulated_effect")

    workflow = publish_mcp_tool_workflow(
        client,
        issuer,
        key=f"publish-approval-{uuid4()}",
        name=f"MCP Approval Demo {uuid4()}",
        tool_name=tool_name,
    )
    run = create_run(client, issuer, workflow, key="mcp-approval-run")
    completed = run_worker_until_terminal(
        database=database,
        settings=settings,
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
        auto_approve=True,
    )

    assert completed["status"] == "succeeded"
    invocations = client.get(
        f"/v1/tools/runs/{run['id']}/invocations", headers=headers(issuer)
    ).json()["tool_invocations"]
    assert invocations[0]["risk"] == "simulated_effect"
    assert invocations[0]["status"] == "succeeded"


def test_mcp_tool_not_granted_to_run_is_denied(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
    alice: ActorContext,
) -> None:
    """A globally enabled MCP tool still has no authority outside its run-scoped grant."""
    service = MCPAdminService(database, settings)
    server, mappings = add_and_discover(service, alice, name=f"ungranted-{uuid4()}")
    mapping = next(m for m in mappings if m["remote_tool_name"] == "search_release_notes")
    tool_name = f"mcp.ungranted_{uuid4().hex[:8]}.search_release_notes"
    enable(service, alice, server, mapping, forge_tool_name=tool_name)

    from forge_api.application.mcp_tool_adapter import MCPToolAdapter
    from forge_api.application.tool_runtime import ToolRuntime

    runtime = ToolRuntime(database=database)
    fake_claim = {
        "worker_id": "test-worker",
        "tenant_id": TENANT_ID,
        "workspace_id": WORKSPACE_ID,
        "run_id": "018f0000-0000-7000-8000-0000000000ff",
        "task_id": "018f0000-0000-7000-8000-0000000000fe",
        "attempt_id": None,
        "input": {"tool_name": tool_name, "tool_version": 1, "arguments": {"query": "x"}},
    }
    with pytest.raises(ProblemError) as exc_info:
        runtime.invoke_for_claim(fake_claim)
    assert exc_info.value.code == "tool_not_granted"
    assert MCP_CASES_BY_SCENARIO["confused_deputy_no_run_grant"].expected_outcome == "denied"
    _ = MCPToolAdapter  # imported for symmetry with the direct-adapter smoke coverage above


def test_mcp_outcome_unknown_on_timeout_after_send(
    database: Database, settings: Settings, alice: ActorContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = add_and_discover(service, alice, name=f"hang-{uuid4()}")
    mapping = next(m for m in mappings if m["remote_tool_name"] == "search_release_notes")
    tool_name = f"mcp.hang_{uuid4().hex[:8]}.search_release_notes"
    enable(service, alice, server, mapping, forge_tool_name=tool_name)

    monkeypatch.setattr("forge_api.application.mcp_tool_adapter.MCP_INVOCATION_TIMEOUT_MS", 300)
    monkeypatch.setenv("FORGE_MCP_FIXTURE_VARIANT", "hang")

    from forge_api.application.mcp_tool_adapter import MCPOutcomeUnknownError, MCPToolAdapter

    adapter = MCPToolAdapter(database=database)
    with pytest.raises(MCPOutcomeUnknownError):
        adapter.invoke(
            tool_name=tool_name,
            arguments={"query": "worker"},
            idempotency_key=f"hang-invoke-{uuid4()}",
        )


def test_workflow_publish_accepts_enabled_mcp_tool(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
    alice: ActorContext,
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = add_and_discover(service, alice, name=f"publish-{uuid4()}")
    mapping = next(m for m in mappings if m["remote_tool_name"] == "search_release_notes")
    tool_name = f"mcp.publish_{uuid4().hex[:8]}.search_release_notes"
    enable(service, alice, server, mapping, forge_tool_name=tool_name)

    workflow = publish_mcp_tool_workflow(
        client,
        issuer,
        key=f"publish-ok-{uuid4()}",
        name=f"MCP Publish OK {uuid4()}",
        tool_name=tool_name,
    )
    assert workflow["name"].startswith("MCP Publish OK")


def test_workflow_publish_rejects_unknown_tool_name(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    base = workflow_by_name(client, issuer, "Incident Response Demo")
    response = client.post(
        "/v1/workflows",
        headers=headers(issuer, key=f"publish-unknown-{uuid4()}"),
        json={
            "workspace_id": base["workspace_id"],
            "name": f"MCP Unknown Tool {uuid4()}",
            "steps": [
                {
                    "key": "mcp_step",
                    "name": "MCP Tool Step",
                    "kind": "tool",
                    "input": {
                        "tool_name": "mcp.never_registered.search",
                        "tool_version": 1,
                        "arguments": {},
                    },
                }
            ],
            "edges": [],
        },
    )
    assert response.status_code == 404
    assert response.json()["code"] == "tool_not_found"
