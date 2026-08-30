import json
from typing import Any, cast
from urllib.parse import urlparse

from redis import Redis

from forge_api.application.reliability_service import (
    OutboxDispatcher,
    RecoveryService,
    WorkerConsumer,
)
from forge_api.config import Settings
from forge_api.domain.reliability import RetryPolicy
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.queue import RedisStreamQueue
from forge_api.infrastructure.workflow_repositories import (
    OutboxRepository,
    RunRepository,
    WorkerRepository,
    WorkflowRepository,
)
from forge_api.scripts.seed import main as seed_main

TENANT_ID = "018f0000-0000-7000-8000-000000000001"
WORKSPACE_ID = "018f0000-0000-7000-8000-000000000101"
SEEDED_WORKFLOW_VERSION_ID = "018f0000-0000-7000-8000-000000000202"


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
        raise RuntimeError("Seeded Alice user was not found. Run pnpm db:seed first.")
    return str(row["id"])


def _redis(settings: Settings) -> Redis:
    return Redis.from_url(settings.redis_url, decode_responses=True)


def _queue(settings: Settings) -> RedisStreamQueue:
    return RedisStreamQueue(
        redis_url=settings.redis_url,
        stream_name=settings.queue_stream,
        group_name=settings.queue_group,
    )


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


def _create_failure_workflow(database: Database, actor_id: str) -> dict[str, Any]:
    with database.transaction(tenant_id=TENANT_ID, actor_id=actor_id) as conn:
        return WorkflowRepository(conn).create_published_version(
            tenant_id=TENANT_ID,
            workspace_id=WORKSPACE_ID,
            actor_id=actor_id,
            name="Local Failure Recovery Demo",
            steps=[
                {
                    "key": "fail",
                    "name": "Always fail",
                    "kind": "deterministic",
                    "input": {"failure_mode": "always_fail"},
                }
            ],
            edges=[],
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
    queue: RedisStreamQueue,
    run_id: str,
    max_ticks: int = 20,
) -> str:
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    consumer = WorkerConsumer(
        database=database,
        queue=queue,
        worker_id=settings.worker_id,
        lease_seconds=settings.task_lease_seconds,
        retry_policy=RetryPolicy(max_attempts=settings.task_max_attempts),
    )
    recovery = RecoveryService(database=database, worker_id=settings.worker_id)
    for _ in range(max_ticks):
        dispatcher.dispatch_once()
        consumer.consume_once(block_ms=50)
        recovery.scan_once()
        status = _run_status(database, actor_id, run_id)
        if status in {"succeeded", "failed", "cancelled"}:
            return status
    return _run_status(database, actor_id, run_id)


def _envelope_for_run(database: Database, settings: Settings, run_id: str) -> Any:
    with database.transaction(worker_id=settings.worker_id) as conn:
        envelopes = OutboxRepository(conn).due_unpublished(limit=100)
    for envelope in envelopes:
        if envelope.payload.get("run_id") == run_id:
            return envelope
    raise RuntimeError(f"No unpublished outbox message found for run {run_id}.")


def demo_redis_loss(database: Database, settings: Settings, actor_id: str) -> None:
    redis = _redis(settings)
    redis.delete(settings.queue_stream)
    queue = _queue(settings)
    run = _create_run(
        database=database,
        actor_id=actor_id,
        workflow_version_id=SEEDED_WORKFLOW_VERSION_ID,
        objective="Demonstrate Redis loss recovery.",
    )
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    published_before_loss = dispatcher.dispatch_once()
    stream_length_before_loss = cast(int, redis.xlen(settings.queue_stream))
    redis.delete(settings.queue_stream)
    queue = _queue(settings)
    recovery = RecoveryService(database=database, worker_id=settings.worker_id).scan_once()
    published_after_recovery = OutboxDispatcher(
        database=database,
        queue=queue,
        worker_id=settings.worker_id,
    ).dispatch_once()
    terminal_status = _drive_worker(
        database=database,
        settings=settings,
        actor_id=actor_id,
        queue=queue,
        run_id=str(run["id"]),
    )
    _print(
        "redis_loss_recovery",
        {
            "published_before_loss": published_before_loss,
            "stream_length_before_loss": stream_length_before_loss,
            "recovery": recovery,
            "published_after_recovery": published_after_recovery,
            "terminal_status": terminal_status,
        },
    )


def demo_stale_lease(database: Database, settings: Settings, actor_id: str) -> None:
    redis = _redis(settings)
    redis.delete(settings.queue_stream)
    queue = _queue(settings)
    run = _create_run(
        database=database,
        actor_id=actor_id,
        workflow_version_id=SEEDED_WORKFLOW_VERSION_ID,
        objective="Demonstrate stale lease fencing.",
    )
    envelope = _envelope_for_run(database, settings, str(run["id"]))
    with database.transaction(worker_id=settings.worker_id) as conn:
        claim = WorkerRepository(conn, lease_seconds=-1).claim_task(
            envelope=envelope,
            worker_id=settings.worker_id,
            actor_id=actor_id,
        )
    if claim is None:
        raise RuntimeError("Expected a claim for the stale-lease demo.")
    with database.transaction(worker_id=settings.worker_id) as conn:
        stale_commit_accepted = WorkerRepository(conn).complete_attempt(
            claim=claim,
            result={"demo": "stale"},
            actor_id=actor_id,
        )
    recovery = RecoveryService(database=database, worker_id=settings.worker_id).scan_once()
    terminal_status = _drive_worker(
        database=database,
        settings=settings,
        actor_id=actor_id,
        queue=queue,
        run_id=str(run["id"]),
    )
    _print(
        "stale_lease_fencing",
        {
            "stale_commit_accepted": stale_commit_accepted,
            "recovery": recovery,
            "terminal_status_after_recovery": terminal_status,
        },
    )


def demo_dead_letter_requeue(database: Database, settings: Settings, actor_id: str) -> None:
    redis = _redis(settings)
    redis.delete(settings.queue_stream)
    queue = _queue(settings)
    workflow = _create_failure_workflow(database, actor_id)
    run = _create_run(
        database=database,
        actor_id=actor_id,
        workflow_version_id=str(workflow["id"]),
        objective="Demonstrate dead-letter inspection and requeue.",
    )
    failed_status = _drive_worker(
        database=database,
        settings=settings,
        actor_id=actor_id,
        queue=queue,
        run_id=str(run["id"]),
    )
    with database.transaction(actor_id=actor_id) as conn:
        dead_letters = RunRepository(conn).list_dead_letters_for_actor(actor_id=actor_id)
        selected = next(
            dead_letter for dead_letter in dead_letters if dead_letter["run_id"] == run["id"]
        )
    with database.transaction(tenant_id=TENANT_ID, actor_id=actor_id) as conn:
        requeued = RunRepository(conn).requeue_dead_letter(
            actor_id=actor_id,
            dead_letter_id=str(selected["id"]),
        )
    _print(
        "dead_letter_requeue",
        {
            "failed_status": failed_status,
            "dead_letter_reason": selected["reason"],
            "sanitized_payload_keys": sorted(selected["sanitized_payload"].keys()),
            "status_after_requeue": requeued["status"],
        },
    )


def main() -> None:
    settings = Settings()
    settings.assert_zero_cost_safe()
    _assert_local_url(settings.database_url, label="FORGE_DATABASE_URL")
    _assert_local_url(settings.migration_database_url, label="FORGE_MIGRATION_DATABASE_URL")
    _assert_local_url(settings.redis_url, label="FORGE_REDIS_URL")
    seed_main()
    database = Database(settings.database_url)
    actor_id = _alice_id(database, settings)
    demo_redis_loss(database, settings, actor_id)
    demo_stale_lease(database, settings, actor_id)
    demo_dead_letter_requeue(database, settings, actor_id)


if __name__ == "__main__":
    main()
