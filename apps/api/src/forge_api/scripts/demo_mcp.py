import json
import os
import sys
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from redis import Redis

from forge_api.api.errors import ProblemError
from forge_api.application.approval_service import ApprovalService
from forge_api.application.mcp_service import MCPAdminService
from forge_api.application.mcp_tool_adapter import MCPOutcomeUnknownError, MCPToolAdapter
from forge_api.application.reliability_service import OutboxDispatcher, WorkerConsumer
from forge_api.config import Settings
from forge_api.domain.approvals import ApprovalDecisionValue
from forge_api.domain.identity import ActorContext, Role
from forge_api.domain.mcp import MCPConnectionPolicy
from forge_api.domain.reliability import RetryPolicy
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.queue import RedisStreamQueue
from forge_api.infrastructure.tool_repositories import (
    ToolInvocationRepository,
    ToolRegistryRepository,
)
from forge_api.infrastructure.workflow_repositories import RunRepository, WorkflowRepository
from forge_api.scripts.seed import TENANT_ID, WORKSPACE_ID
from forge_api.scripts.seed import main as seed_main

STDIO_COMMAND = [sys.executable, "-m", "forge_api.scripts.mcp_fixture_server"]


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


def _queue(settings: Settings) -> RedisStreamQueue:
    return RedisStreamQueue(
        redis_url=settings.redis_url,
        stream_name=settings.queue_stream,
        group_name=settings.queue_group,
    )


def _clear_queue(settings: Settings) -> None:
    Redis.from_url(settings.redis_url, decode_responses=True).delete(settings.queue_stream)


def _publish_mcp_workflow(
    database: Database, actor_id: str, *, name: str, tool_name: str
) -> dict[str, Any]:
    with database.transaction(tenant_id=TENANT_ID, actor_id=actor_id) as conn:
        return WorkflowRepository(conn).create_published_version(
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            actor_id=actor_id,
            name=name,
            steps=[
                {
                    "key": "mcp_step",
                    "name": "MCP tool step",
                    "kind": "tool",
                    "input": {
                        "tool_name": tool_name,
                        "tool_version": 1,
                        "arguments": {"query": "worker", "limit": 3},
                    },
                }
            ],
            edges=[],
        )


def _create_run(
    database: Database, actor_id: str, workflow_version_id: str, objective: str
) -> dict[str, Any]:
    with database.transaction(actor_id=actor_id) as conn:
        workflow = WorkflowRepository(conn).get_version_for_actor(
            actor_id=actor_id, version_id=workflow_version_id
        )
    with database.transaction(tenant_id=TENANT_ID, actor_id=actor_id) as conn:
        return RunRepository(conn).create_run(
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            actor_id=actor_id,
            workflow_version=workflow,
            objective=objective,
            constraints={},
        )


def _drive_worker(
    *,
    database: Database,
    settings: Settings,
    actor_id: str,
    approver: ActorContext | None,
    run_id: str,
) -> str:
    queue = _queue(settings)
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
        outcome = consumer.consume_once(block_ms=50)
        if outcome == "waiting_approval" and approver is not None:
            with database.transaction(actor_id=actor_id) as conn:
                approval = conn.execute(
                    "select * from approval_requests where run_id = %s and status = 'pending' "
                    "order by created_at desc limit 1",
                    (run_id,),
                ).fetchone()
            if approval is not None:
                ApprovalService(database).decide(
                    approver,
                    str(approval["id"]),
                    decision=ApprovalDecisionValue.APPROVED,
                    reason="Ava approves the exact simulated MCP effect.",
                    expected_version=int(approval["request_version"]),
                    idempotency_key=f"demo-mcp-approve-{approval['id']}",
                )
        with database.transaction(actor_id=actor_id) as conn:
            run = RunRepository(conn).get_run_for_actor(actor_id=actor_id, run_id=run_id)
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            return str(run["status"])
    return str(run["status"])


def _invocations(database: Database, actor_id: str, run_id: str) -> list[dict[str, Any]]:
    with database.transaction(actor_id=actor_id) as conn:
        return ToolInvocationRepository(conn).list_invocations_for_actor(
            actor_id=actor_id, run_id=run_id
        )


def _evidence(database: Database, actor_id: str, run_id: str) -> list[dict[str, Any]]:
    with database.transaction(actor_id=actor_id) as conn:
        return ToolInvocationRepository(conn).list_evidence_for_actor(
            actor_id=actor_id, run_id=run_id
        )


def _add_and_discover(
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
        idempotency_key=f"demo-add-{name}-{uuid4()}",
    )["server"]
    discovery = service.discover_server(
        alice, server["id"], idempotency_key=f"demo-discover-{name}-{uuid4()}"
    )
    return server, discovery["mappings"]


def demo_add_discover_enable_and_run(
    database: Database, settings: Settings, alice: ActorContext, ava: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = _add_and_discover(service, alice, name="forge-release-notes")
    health = service.test_server(alice, server["id"])
    _print(
        "mcp_server_added_tested_discovered",
        {
            "server_status": server["status"],
            "health_check": {
                "healthy": health["healthy"],
                "server_name": health.get("server_name"),
            },
            "discovered_tools": sorted(m["remote_tool_name"] for m in mappings),
            "mapping_statuses": sorted({m["status"] for m in mappings}),
        },
    )

    quarantined_tool_name = "search_release_notes"
    try:
        MCPToolAdapter(database=database).invoke(
            tool_name=quarantined_tool_name,
            arguments={"query": "x"},
            idempotency_key="demo-quarantine",
        )
    except ProblemError as exc:
        _print(
            "discovered_tool_quarantined_before_review",
            {
                "attempted_tool_name": quarantined_tool_name,
                "code": exc.code,
                "status_code": exc.status_code,
            },
        )
    else:
        raise RuntimeError("Un-reviewed discovered MCP tool executed; quarantine failed.")

    mapping = next(m for m in mappings if m["remote_tool_name"] == "search_release_notes")
    enabled = service.enable_mapping(
        alice,
        server["id"],
        mapping["id"],
        forge_tool_name="mcp.forge_release_notes.search_release_notes",
        risk="read_only",
        expected_schema_hash=mapping["schema_hash"],
        expected_version=mapping["version"],
        idempotency_key=f"demo-mcp-enable-{uuid4()}",
    )
    workflow = _publish_mcp_workflow(
        database, alice.user_id, name="MCP Interop Demo", tool_name=enabled["tool_name"]
    )
    run = _create_run(
        database, alice.user_id, str(workflow["id"]), "Demonstrate real MCP tool interoperability."
    )
    status = _drive_worker(
        database=database,
        settings=settings,
        actor_id=alice.user_id,
        approver=ava,
        run_id=str(run["id"]),
    )
    invocations = _invocations(database, alice.user_id, str(run["id"]))
    evidence = _evidence(database, alice.user_id, str(run["id"]))
    _print(
        "mcp_tool_executed_through_real_run",
        {
            "terminal_status": status,
            "invocation_statuses": {inv["tool_name"]: inv["status"] for inv in invocations},
            "mcp_provenance": invocations[0].get("mcp_provenance") if invocations else None,
            "trust_labels": sorted({item["trust_label"] for item in evidence}),
            "paid_provider_calls": 0,
        },
    )


def demo_simulated_effect_requires_approval(
    database: Database, settings: Settings, alice: ActorContext, ava: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = _add_and_discover(
        service, alice, name=f"release-notes-approval-{uuid4().hex[:6]}"
    )
    mapping = next(m for m in mappings if m["remote_tool_name"] == "search_release_notes")
    enabled = service.enable_mapping(
        alice,
        server["id"],
        mapping["id"],
        forge_tool_name="mcp.forge_release_notes_approval.search_release_notes",
        risk="simulated_effect",
        expected_schema_hash=mapping["schema_hash"],
        expected_version=mapping["version"],
        idempotency_key=f"demo-mcp-enable-sim-{uuid4()}",
    )
    workflow = _publish_mcp_workflow(
        database, alice.user_id, name="MCP Approval Demo", tool_name=enabled["tool_name"]
    )
    run = _create_run(
        database, alice.user_id, str(workflow["id"]), "Demonstrate approval-gated MCP tool."
    )
    status = _drive_worker(
        database=database,
        settings=settings,
        actor_id=alice.user_id,
        approver=ava,
        run_id=str(run["id"]),
    )
    invocations = _invocations(database, alice.user_id, str(run["id"]))
    _print(
        "mcp_simulated_effect_tool_required_approval",
        {
            "terminal_status": status,
            "risk": invocations[0]["risk"] if invocations else None,
            "invocation_status": invocations[0]["status"] if invocations else None,
        },
    )


def demo_malicious_content_contained(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    os.environ["FORGE_MCP_FIXTURE_VARIANT"] = "adversarial"
    service = MCPAdminService(database, settings)
    server, mappings = _add_and_discover(service, alice, name=f"adversarial-{uuid4().hex[:6]}")
    flagged = next(m for m in mappings if m["remote_tool_name"] == "read_flagged_advisory")
    enabled = service.enable_mapping(
        alice,
        server["id"],
        flagged["id"],
        forge_tool_name="mcp.forge_adversarial.read_flagged_advisory",
        risk="read_only",
        expected_schema_hash=flagged["schema_hash"],
        expected_version=flagged["version"],
        idempotency_key=f"demo-mcp-enable-adv-{uuid4()}",
    )
    output = MCPToolAdapter(database=database).invoke(
        tool_name=enabled["tool_name"],
        arguments={},
        idempotency_key=f"demo-mcp-adv-invoke-{uuid4()}",
    )
    with database.transaction(worker_id="demo-worker") as conn:
        row = ToolRegistryRepository(conn).try_resolve(name=enabled["tool_name"], version=1)
    os.environ["FORGE_MCP_FIXTURE_VARIANT"] = "default"
    contains_injection = "ignore previous instructions" in output["advisory"].lower()
    _print(
        "malicious_mcp_content_flagged_and_contained",
        {
            "tool_output_contains_injection_phrase": contains_injection,
            "trust_label": row["trust_label"] if row else None,
            "note": "flagging is advisory only; containment is the untrusted trust label",
        },
    )


def demo_schema_drift_blocks_execution(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = _add_and_discover(service, alice, name=f"drift-{uuid4().hex[:6]}")
    mapping = next(m for m in mappings if m["remote_tool_name"] == "search_release_notes")
    tool_name = "mcp.forge_drift.search_release_notes"
    service.enable_mapping(
        alice,
        server["id"],
        mapping["id"],
        forge_tool_name=tool_name,
        risk="read_only",
        expected_schema_hash=mapping["schema_hash"],
        expected_version=mapping["version"],
        idempotency_key=f"demo-mcp-enable-drift-{uuid4()}",
    )
    with database.transaction(worker_id="demo-worker") as conn:
        before = ToolRegistryRepository(conn).try_resolve(name=tool_name, version=1)

    os.environ["FORGE_MCP_FIXTURE_VARIANT"] = "schema_changed"
    redisco = service.discover_server(
        alice, server["id"], idempotency_key=f"demo-mcp-redisc-{uuid4()}"
    )
    os.environ["FORGE_MCP_FIXTURE_VARIANT"] = "default"
    drifted = next(
        m for m in redisco["mappings"] if m["remote_tool_name"] == "search_release_notes"
    )
    with database.transaction(worker_id="demo-worker") as conn:
        after = ToolRegistryRepository(conn).try_resolve(name=tool_name, version=1)

    reenabled = service.enable_mapping(
        alice,
        server["id"],
        drifted["id"],
        forge_tool_name=tool_name,
        risk="read_only",
        expected_schema_hash=drifted["schema_hash"],
        expected_version=drifted["version"],
        idempotency_key=f"demo-mcp-reenable-drift-{uuid4()}",
    )
    _print(
        "mcp_schema_drift_detected_and_re_enabled",
        {
            "before_drift_resolvable": before is not None,
            "mapping_status_after_redetect": drifted["status"],
            "after_drift_resolvable_at_old_version": after is not None,
            "new_pinned_version": reenabled["tool_version"],
        },
    )


def demo_zero_cost_and_ssrf_boundaries(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    try:
        service.add_server(
            alice,
            workspace_id=WORKSPACE_ID,
            name=f"remote-demo-{uuid4()}",
            transport="http",
            url="https://example.com/mcp",
            command=None,
            auth_secret_reference=None,
            idempotency_key=f"demo-remote-{uuid4()}",
        )
    except ProblemError as exc:
        remote_denied = {"code": exc.code, "status_code": exc.status_code}
    else:
        raise RuntimeError("Remote MCP transport was not denied on the zero-cost path.")

    ssrf_denied: list[str] = []
    for url in ["http://example.com/mcp", "https://127.0.0.1/mcp", "https://169.254.169.254/mcp"]:
        try:
            MCPConnectionPolicy().validate(transport="http", url=url, command=None)
        except ProblemError as exc:
            ssrf_denied.append(f"{url} -> {exc.code}")

    try:
        MCPConnectionPolicy().validate(
            transport="stdio", url=None, command=["/bin/sh", "-c", "echo hi"]
        )
    except ProblemError as exc:
        stdio_denied = {"code": exc.code}
    else:
        raise RuntimeError("Arbitrary stdio command was not denied.")

    _print(
        "mcp_zero_cost_and_ssrf_boundaries",
        {
            "remote_transport_denied": remote_denied,
            "ssrf_url_denials": ssrf_denied,
            "arbitrary_stdio_denied": stdio_denied,
            "paid_provider_calls": 0,
        },
    )


def demo_viewer_cannot_administer(
    database: Database, settings: Settings, bob: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    try:
        service.add_server(
            bob,
            workspace_id=WORKSPACE_ID,
            name=f"viewer-attempt-{uuid4()}",
            transport="stdio",
            url=None,
            command=STDIO_COMMAND,
            auth_secret_reference=None,
            idempotency_key=f"demo-viewer-{uuid4()}",
        )
    except ProblemError as exc:
        _print(
            "viewer_cannot_administer_mcp",
            {"code": exc.code, "status_code": exc.status_code},
        )
    else:
        raise RuntimeError("Viewer was able to administer an MCP server.")


def demo_outcome_unknown_on_timeout(
    database: Database, settings: Settings, alice: ActorContext
) -> None:
    service = MCPAdminService(database, settings)
    server, mappings = _add_and_discover(service, alice, name=f"hang-{uuid4().hex[:6]}")
    mapping = next(m for m in mappings if m["remote_tool_name"] == "search_release_notes")
    tool_name = "mcp.forge_hang.search_release_notes"
    service.enable_mapping(
        alice,
        server["id"],
        mapping["id"],
        forge_tool_name=tool_name,
        risk="read_only",
        expected_schema_hash=mapping["schema_hash"],
        expected_version=mapping["version"],
        idempotency_key=f"demo-mcp-enable-hang-{uuid4()}",
    )
    import forge_api.application.mcp_tool_adapter as adapter_module

    original_timeout = adapter_module.MCP_INVOCATION_TIMEOUT_MS
    adapter_module.MCP_INVOCATION_TIMEOUT_MS = 300
    os.environ["FORGE_MCP_FIXTURE_VARIANT"] = "hang"
    try:
        MCPToolAdapter(database=database).invoke(
            tool_name=tool_name,
            arguments={"query": "worker"},
            idempotency_key=f"demo-hang-{uuid4()}",
        )
    except MCPOutcomeUnknownError as exc:
        _print(
            "mcp_outcome_unknown_on_timeout_after_send",
            {"reconciliation_required": True, "detail": str(exc)[:120]},
        )
    else:
        raise RuntimeError("Timeout-after-send did not raise MCPOutcomeUnknownError.")
    finally:
        os.environ["FORGE_MCP_FIXTURE_VARIANT"] = "default"
        adapter_module.MCP_INVOCATION_TIMEOUT_MS = original_timeout


def main() -> None:
    settings = Settings()
    settings.assert_zero_cost_safe()
    _assert_local_url(settings.database_url, label="FORGE_DATABASE_URL")
    _assert_local_url(settings.migration_database_url, label="FORGE_MIGRATION_DATABASE_URL")
    _assert_local_url(settings.redis_url, label="FORGE_REDIS_URL")
    os.environ["FORGE_MCP_FIXTURE_VARIANT"] = "default"
    seed_main()
    _clear_queue(settings)
    database = Database(settings.database_url)
    alice = _actor(database, settings, "alice", Role.TENANT_ADMIN)
    ava = _actor(database, settings, "ava", Role.APPROVER)
    bob = _actor(database, settings, "bob", Role.VIEWER)

    demo_add_discover_enable_and_run(database, settings, alice, ava)
    demo_simulated_effect_requires_approval(database, settings, alice, ava)
    demo_malicious_content_contained(database, settings, alice)
    demo_schema_drift_blocks_execution(database, settings, alice)
    demo_zero_cost_and_ssrf_boundaries(database, settings, alice)
    demo_viewer_cannot_administer(database, settings, bob)
    demo_outcome_unknown_on_timeout(database, settings, alice)
    _print("phase11_zero_cost_summary", {"paid_provider_calls": 0, "remote_mcp_servers_dialed": 0})


if __name__ == "__main__":
    main()
