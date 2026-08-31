import json
from typing import Any
from urllib.parse import urlparse

from redis import Redis

from forge_api.api.errors import ProblemError
from forge_api.application.approval_service import ApprovalService
from forge_api.application.reliability_service import OutboxDispatcher, WorkerConsumer
from forge_api.application.workflow_service import WorkflowService
from forge_api.config import Settings
from forge_api.domain.approvals import ApprovalDecisionValue
from forge_api.domain.identity import ActorContext, Role
from forge_api.domain.reliability import RetryPolicy
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.queue import RedisStreamQueue
from forge_api.infrastructure.tool_repositories import ToolInvocationRepository
from forge_api.infrastructure.workflow_repositories import RunRepository, WorkflowRepository
from forge_api.scripts.seed import TENANT_ID, TOOL_WORKFLOW_VERSION_ID, WORKSPACE_ID
from forge_api.scripts.seed import main as seed_main


def _assert_local_url(url: str, *, label: str) -> None:
    parsed = urlparse(url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(f"{label} must point at a loopback host for this demo.")


def _print(action: str, result: dict[str, Any]) -> None:
    print(json.dumps({"action": action, "result": result}, sort_keys=True))


def _alice_id(database: Database, settings: Settings) -> str:
    with database.transaction(actor_id="00000000-0000-0000-0000-000000000000") as conn:
        row = conn.execute(
            """
            select id from users
            where external_issuer = %s and external_subject = 'oidc|alice'
            """,
            (settings.oidc_issuer,),
        ).fetchone()
    if row is None:
        raise RuntimeError("Seeded Alice user was not found.")
    return str(row["id"])


def _user_id(database: Database, settings: Settings, subject: str) -> str:
    with database.transaction(actor_id="00000000-0000-0000-0000-000000000000") as conn:
        row = conn.execute(
            """
            select id from users
            where external_issuer = %s and external_subject = %s
            """,
            (settings.oidc_issuer, f"oidc|{subject}"),
        ).fetchone()
    if row is None:
        raise RuntimeError(f"Seeded {subject} user was not found.")
    return str(row["id"])


def _alice_actor(database: Database, settings: Settings) -> ActorContext:
    actor_id = _alice_id(database, settings)
    return ActorContext(
        user_id=actor_id,
        external_subject="oidc|alice",
        email="alice@forge.local",
        display_name="Alice Admin",
        tenant_ids=frozenset({TENANT_ID}),
        workspace_roles={WORKSPACE_ID: Role.TENANT_ADMIN},
    )


def _ava_actor(database: Database, settings: Settings) -> ActorContext:
    actor_id = _user_id(database, settings, "ava")
    return ActorContext(
        user_id=actor_id,
        external_subject="oidc|ava",
        email="ava@forge.local",
        display_name="Ava Approver",
        tenant_ids=frozenset({TENANT_ID}),
        workspace_roles={WORKSPACE_ID: Role.APPROVER},
    )


def _queue(settings: Settings) -> RedisStreamQueue:
    return RedisStreamQueue(
        redis_url=settings.redis_url,
        stream_name=settings.queue_stream,
        group_name=settings.queue_group,
    )


def _clear_queue(settings: Settings) -> None:
    Redis.from_url(settings.redis_url, decode_responses=True).delete(settings.queue_stream)


def _create_run(
    *,
    database: Database,
    actor_id: str,
    workflow_version_id: str,
    objective: str,
) -> dict[str, Any]:
    with database.transaction(actor_id=actor_id) as conn:
        workflow = WorkflowRepository(conn).get_version_for_actor(
            actor_id=actor_id,
            version_id=workflow_version_id,
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


def _run_status(database: Database, actor_id: str, run_id: str) -> str:
    with database.transaction(actor_id=actor_id) as conn:
        run = RunRepository(conn).get_run_for_actor(actor_id=actor_id, run_id=run_id)
    return str(run["status"])


def _drive_worker(
    *,
    database: Database,
    settings: Settings,
    actor_id: str,
    approver: ActorContext | None = None,
    run_id: str,
    max_ticks: int = 80,
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
    for _ in range(max_ticks):
        dispatcher.dispatch_once()
        outcome = consumer.consume_once(block_ms=50)
        if outcome == "waiting_approval" and approver is not None:
            approval = _pending_approval(database, approver.user_id, run_id)
            ApprovalService(database).decide(
                approver,
                str(approval["id"]),
                decision=ApprovalDecisionValue.APPROVED,
                reason="Ava approves exact local simulated effect.",
                expected_version=int(approval["request_version"]),
                idempotency_key=f"demo-approve-{approval['id']}",
            )
        status = _run_status(database, actor_id, run_id)
        if status in {"succeeded", "failed", "cancelled"}:
            return status
    return _run_status(database, actor_id, run_id)


def _pending_approval(database: Database, actor_id: str, run_id: str) -> dict[str, Any]:
    with database.transaction(actor_id=actor_id) as conn:
        approvals = conn.execute(
            """
            select *
            from approval_requests
            where run_id = %s and status = 'pending'
            order by created_at desc
            limit 1
            """,
            (run_id,),
        ).fetchone()
    if approvals is None:
        raise RuntimeError("Expected pending approval was not found.")
    return dict(approvals)


def _list_invocations(database: Database, actor_id: str, run_id: str) -> list[dict[str, Any]]:
    with database.transaction(actor_id=actor_id) as conn:
        return ToolInvocationRepository(conn).list_invocations_for_actor(
            actor_id=actor_id,
            run_id=run_id,
        )


def _list_evidence(database: Database, actor_id: str, run_id: str) -> list[dict[str, Any]]:
    with database.transaction(actor_id=actor_id) as conn:
        return ToolInvocationRepository(conn).list_evidence_for_actor(
            actor_id=actor_id,
            run_id=run_id,
        )


def demo_success(
    database: Database,
    settings: Settings,
    actor_id: str,
    approver: ActorContext,
) -> None:
    run = _create_run(
        database=database,
        actor_id=actor_id,
        workflow_version_id=TOOL_WORKFLOW_VERSION_ID,
        objective="Demonstrate typed tool runtime success.",
    )
    status = _drive_worker(
        database=database,
        settings=settings,
        actor_id=actor_id,
        approver=approver,
        run_id=str(run["id"]),
    )
    invocations = _list_invocations(database, actor_id, str(run["id"]))
    evidence = _list_evidence(database, actor_id, str(run["id"]))
    _print(
        "typed_tool_success",
        {
            "terminal_status": status,
            "invocation_statuses": {
                str(invocation["tool_name"]): str(invocation["status"])
                for invocation in invocations
            },
            "trust_labels": sorted({str(item["trust_label"]) for item in evidence}),
            "evidence_sources": sorted({str(item["source_name"]) for item in evidence}),
            "paid_provider_calls": 0,
        },
    )


def demo_invalid_schema(database: Database, actor: ActorContext) -> None:
    try:
        WorkflowService(database).create_published_version(
            actor,
            "demo-invalid-tool-schema",
            {
                "workspace_id": WORKSPACE_ID,
                "name": "Invalid Tool Schema Demo",
                "steps": [
                    {
                        "key": "invalid",
                        "name": "Invalid",
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
    except ProblemError as exc:
        _print(
            "invalid_tool_schema_denied",
            {
                "denied_before_adapter_execution": True,
                "status_code": exc.status_code,
                "code": exc.code,
                "message": exc.message,
            },
        )
    else:
        raise RuntimeError("Invalid tool schema was accepted unexpectedly.")


def demo_outcome_unknown(database: Database, settings: Settings, actor_id: str) -> None:
    with database.transaction(tenant_id=TENANT_ID, actor_id=actor_id) as conn:
        workflow = WorkflowRepository(conn).create_published_version(
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            actor_id=actor_id,
            name="Outcome Unknown Tool Demo",
            steps=[
                {
                    "key": "ambiguous_effect",
                    "name": "Ambiguous simulated effect",
                    "kind": "tool",
                    "input": {
                        "tool_name": "ticket.create_simulated",
                        "tool_version": 1,
                        "arguments": {
                            "title": "Investigate ambiguous local provider result",
                            "severity": "medium",
                            "dry_run": True,
                            "simulate_outcome_unknown": True,
                        },
                    },
                }
            ],
            edges=[],
        )
    run = _create_run(
        database=database,
        actor_id=actor_id,
        workflow_version_id=str(workflow["id"]),
        objective="Demonstrate outcome-unknown tracking.",
    )
    status = _drive_worker(
        database=database,
        settings=settings,
        actor_id=actor_id,
        approver=_ava_actor(database, settings),
        run_id=str(run["id"]),
    )
    invocations = _list_invocations(database, actor_id, str(run["id"]))
    _print(
        "outcome_unknown_recorded",
        {
            "terminal_status": status,
            "invocation_statuses": [str(invocation["status"]) for invocation in invocations],
            "error_types": [str(invocation["error_type"]) for invocation in invocations],
        },
    )


def main() -> None:
    settings = Settings()
    settings.assert_zero_cost_safe()
    _assert_local_url(settings.database_url, label="FORGE_DATABASE_URL")
    _assert_local_url(settings.migration_database_url, label="FORGE_MIGRATION_DATABASE_URL")
    _assert_local_url(settings.redis_url, label="FORGE_REDIS_URL")
    seed_main()
    _clear_queue(settings)
    database = Database(settings.database_url)
    actor = _alice_actor(database, settings)
    approver = _ava_actor(database, settings)
    actor_id = actor.user_id
    demo_success(database, settings, actor_id, approver)
    demo_invalid_schema(database, actor)
    demo_outcome_unknown(database, settings, actor_id)


if __name__ == "__main__":
    main()
