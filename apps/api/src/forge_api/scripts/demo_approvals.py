import json
from typing import Any
from urllib.parse import urlparse

from redis import Redis

from forge_api.api.errors import ProblemError
from forge_api.application.approval_service import ApprovalService
from forge_api.application.reliability_service import OutboxDispatcher, WorkerConsumer
from forge_api.config import Settings
from forge_api.domain.approvals import ApprovalDecisionValue, FakeSecretResolver, NetworkPolicy
from forge_api.domain.identity import ActorContext, Role
from forge_api.domain.reliability import RetryPolicy
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.queue import RedisStreamQueue
from forge_api.infrastructure.workflow_repositories import RunRepository, WorkflowRepository
from forge_api.scripts.seed import TENANT_ID, TOOL_WORKFLOW_VERSION_ID, WORKSPACE_ID
from forge_api.scripts.seed import main as seed_main


def _assert_local_url(url: str, *, label: str) -> None:
    parsed = urlparse(url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(f"{label} must point at a loopback host for this demo.")


def _print(action: str, result: dict[str, Any]) -> None:
    print(json.dumps({"action": action, "result": result}, sort_keys=True))


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


def _actor(database: Database, settings: Settings, subject: str, role: Role) -> ActorContext:
    actor_id = _user_id(database, settings, subject)
    return ActorContext(
        user_id=actor_id,
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


def _create_run(database: Database, actor: ActorContext, objective: str) -> dict[str, Any]:
    with database.transaction(actor_id=actor.user_id) as conn:
        workflow = WorkflowRepository(conn).get_version_for_actor(
            actor_id=actor.user_id,
            version_id=TOOL_WORKFLOW_VERSION_ID,
        )
    with database.transaction(tenant_id=TENANT_ID, actor_id=actor.user_id) as conn:
        return RunRepository(conn).create_run(
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            actor_id=actor.user_id,
            workflow_version=workflow,
            objective=objective,
            constraints={},
        )


def _run_status(database: Database, actor: ActorContext, run_id: str) -> str:
    with database.transaction(actor_id=actor.user_id) as conn:
        run = RunRepository(conn).get_run_for_actor(actor_id=actor.user_id, run_id=run_id)
    return str(run["status"])


def _tasks(database: Database, actor: ActorContext, run_id: str) -> list[dict[str, Any]]:
    with database.transaction(actor_id=actor.user_id) as conn:
        rows = conn.execute(
            """
            select step_key, name, kind, status
            from tasks
            where run_id = %s
            order by step_key
            """,
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _events(database: Database, actor: ActorContext, run_id: str) -> list[str]:
    with database.transaction(actor_id=actor.user_id) as conn:
        rows = conn.execute(
            """
            select event_type
            from execution_events
            where run_id = %s
            order by sequence
            """,
            (run_id,),
        ).fetchall()
    return [str(row["event_type"]) for row in rows]


def _drive_worker(
    *,
    database: Database,
    settings: Settings,
    actor: ActorContext,
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
        if outcome == "waiting_approval":
            return outcome
        status = _run_status(database, actor, run_id)
        if status in {"succeeded", "failed", "cancelled"}:
            return status
    return _run_status(database, actor, run_id)


def _pending_approval(
    database: Database,
    approver: ActorContext,
    run_id: str,
) -> dict[str, Any]:
    approvals = ApprovalService(database).list_approvals(approver)
    return next(
        approval
        for approval in approvals
        if approval["run_id"] == run_id and approval["status"] == "pending"
    )


def _approve(
    database: Database,
    approver: ActorContext,
    approval: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    response = ApprovalService(database).decide(
        approver,
        str(approval["id"]),
        decision=ApprovalDecisionValue.APPROVED,
        reason=reason,
        expected_version=int(approval["request_version"]),
        idempotency_key=f"demo-approve-{approval['id']}",
    )
    approval_request = response["approval_request"]
    if not isinstance(approval_request, dict):
        raise RuntimeError("Approval response was invalid.")
    return approval_request


def _reject(
    database: Database,
    approver: ActorContext,
    approval: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    response = ApprovalService(database).decide(
        approver,
        str(approval["id"]),
        decision=ApprovalDecisionValue.REJECTED,
        reason=reason,
        expected_version=int(approval["request_version"]),
        idempotency_key=f"demo-reject-{approval['id']}",
    )
    approval_request = response["approval_request"]
    if not isinstance(approval_request, dict):
        raise RuntimeError("Approval response was invalid.")
    return approval_request


def demo_approval_resume(
    database: Database,
    settings: Settings,
    alice: ActorContext,
    ava: ActorContext,
) -> None:
    run = _create_run(database, alice, "Demonstrate exact-action approval resume.")
    outcome = _drive_worker(
        database=database,
        settings=settings,
        actor=alice,
        run_id=str(run["id"]),
    )
    approval = _pending_approval(database, ava, str(run["id"]))
    _print(
        "approval_requested",
        {
            "worker_outcome": outcome,
            "run_status": _run_status(database, alice, str(run["id"])),
            "waiting_tasks": _tasks(database, alice, str(run["id"])),
            "approval_status": approval["status"],
            "risk": approval["risk"],
            "action_hash": approval["action_hash"],
            "request_version": approval["request_version"],
        },
    )

    try:
        _approve(database, alice, approval, reason="Alice attempts to approve her own request.")
    except ProblemError as exc:
        _print(
            "self_approval_denied",
            {"status_code": exc.status_code, "code": exc.code, "message": exc.message},
        )
    else:
        raise RuntimeError("Self-approval was not denied.")

    approved = _approve(database, ava, approval, reason="Ava approves the exact local action.")
    terminal = _drive_worker(
        database=database,
        settings=settings,
        actor=alice,
        run_id=str(run["id"]),
    )
    consumed = ApprovalService(database).list_approvals(ava)[0]
    _print(
        "approval_consumed_and_run_completed",
        {
            "approved_status": approved["status"],
            "consumed_status": consumed["status"],
            "terminal_status": terminal,
            "events": _events(database, alice, str(run["id"])),
        },
    )


def demo_rejection(
    database: Database,
    settings: Settings,
    alice: ActorContext,
    ava: ActorContext,
) -> None:
    run = _create_run(database, alice, "Demonstrate approval rejection fail-closed.")
    _drive_worker(database=database, settings=settings, actor=alice, run_id=str(run["id"]))
    approval = _pending_approval(database, ava, str(run["id"]))
    rejected = _reject(database, ava, approval, reason="Ava rejects this exact action.")
    _print(
        "approval_rejection_failed_closed",
        {
            "approval_status": rejected["status"],
            "run_status": _run_status(database, alice, str(run["id"])),
            "task_statuses": _tasks(database, alice, str(run["id"])),
        },
    )


def demo_expiry(
    database: Database,
    settings: Settings,
    alice: ActorContext,
    ava: ActorContext,
) -> None:
    run = _create_run(database, alice, "Demonstrate approval expiry fail-closed.")
    _drive_worker(database=database, settings=settings, actor=alice, run_id=str(run["id"]))
    approval = _pending_approval(database, ava, str(run["id"]))
    with database.transaction(tenant_id=TENANT_ID, actor_id=alice.user_id) as conn:
        conn.execute(
            "update approval_requests set expires_at = now() - interval '1 second' where id = %s",
            (approval["id"],),
        )
    try:
        _approve(database, ava, approval, reason="Ava tries to approve an expired request.")
    except ProblemError as exc:
        _print(
            "approval_expiry_failed_closed",
            {
                "status_code": exc.status_code,
                "code": exc.code,
                "run_status": _run_status(database, alice, str(run["id"])),
            },
        )
    else:
        raise RuntimeError("Expired approval was not denied.")


def demo_boundary_guards() -> None:
    network = NetworkPolicy()
    denied_urls = [
        "http://example.com/callback",
        "https://localhost/admin",
        "https://127.0.0.1/admin",
        "https://169.254.169.254/latest/meta-data",
        "https://10.0.0.4/internal",
    ]
    denied: list[str] = []
    for url in denied_urls:
        try:
            network.validate_url(url)
        except ProblemError as exc:
            denied.append(f"{url} -> {exc.code}")
    secret = FakeSecretResolver().resolve_reference("secretref://local/ticket-demo")
    _print(
        "network_and_secret_boundaries",
        {
            "denied": denied,
            "allowed_public_https": network.validate_url("https://example.com/callback"),
            "secret_reference": secret["reference"],
            "secret_material": secret["material"],
            "paid_provider_calls": 0,
        },
    )


def main() -> None:
    settings = Settings()
    settings.assert_zero_cost_safe()
    _assert_local_url(settings.database_url, label="FORGE_DATABASE_URL")
    _assert_local_url(settings.migration_database_url, label="FORGE_MIGRATION_DATABASE_URL")
    _clear_queue(settings)
    seed_main()
    database = Database(settings.database_url)
    alice = _actor(database, settings, "alice", Role.TENANT_ADMIN)
    ava = _actor(database, settings, "ava", Role.APPROVER)

    demo_approval_resume(database, settings, alice, ava)
    demo_rejection(database, settings, alice, ava)
    demo_expiry(database, settings, alice, ava)
    demo_boundary_guards()
    _print("phase6_zero_cost_summary", {"paid_provider_calls": 0, "default_model": "fake"})


if __name__ == "__main__":
    main()
