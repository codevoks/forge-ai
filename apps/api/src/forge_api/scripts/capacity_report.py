"""Phase 13 local load/soak drill: measures REAL throughput and latency for
the deterministic zero-cost path on this machine, then extrapolates a
naive 100x capacity estimate with explicit caveats. This is evidence for
the Temporal ADR and `docs/architecture/scale-observability-cost.md`, not a
production benchmark: one Postgres instance, one Redis instance, no
connection pooling (`Database.transaction` opens a fresh connection per
call — see the "what fails first at 100x" section this report feeds), and
whatever CPU/IO the local dev machine happens to have.
"""

import json
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from redis import Redis

from forge_api.application.reliability_service import OutboxDispatcher, WorkerConsumer
from forge_api.application.run_service import RunService
from forge_api.config import Settings
from forge_api.domain.identity import ActorContext, Role
from forge_api.domain.reliability import RetryPolicy
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.queue import InMemoryQueue
from forge_api.infrastructure.telemetry import ForgeTelemetry
from forge_api.infrastructure.workflow_repositories import WorkflowRepository
from forge_api.scripts.seed import TENANT_ID, WORKSPACE_ID
from forge_api.scripts.seed import main as seed_main

RUN_COUNT = 60
WORKER_COUNT = 4
SOAK_SECONDS = 20


def _assert_local_url(url: str, *, label: str) -> None:
    parsed = urlparse(url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(f"{label} must point at a loopback host for this drill.")


def _print(action: str, result: dict[str, Any]) -> None:
    print(json.dumps({"action": action, "result": result}, sort_keys=True, default=str))


def _actor(database: Database, settings: Settings) -> ActorContext:
    with database.transaction(actor_id="00000000-0000-0000-0000-000000000000") as conn:
        row = conn.execute(
            "select id from users where external_issuer = %s and external_subject = 'oidc|alice'",
            (settings.oidc_issuer,),
        ).fetchone()
    if row is None:
        raise RuntimeError("Seeded Alice user was not found. Run pnpm db:seed first.")
    return ActorContext(
        user_id=str(row["id"]),
        external_subject="oidc|alice",
        email="alice@forge.local",
        display_name="Alice Admin",
        tenant_ids=frozenset({TENANT_ID}),
        workspace_roles={WORKSPACE_ID: Role.TENANT_ADMIN},
    )


@dataclass
class RunTiming:
    run_id: str
    created_at: float
    completed_at: float | None = None


@dataclass
class LoadResult:
    timings: list[RunTiming] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)


def _create_runs(
    *,
    run_service: RunService,
    actor: ActorContext,
    workflow_version_id: str,
    workspace_id: str,
    count: int,
    result: LoadResult,
) -> None:
    for _ in range(count):
        started = time.monotonic()
        run = run_service.create(
            actor,
            f"load-soak-{uuid4()}",
            {
                "workspace_id": workspace_id,
                "workflow_version_id": workflow_version_id,
                "objective": "Phase 13 load/soak drill over the deterministic workflow.",
            },
        )["run"]
        with result.lock:
            result.timings.append(RunTiming(run_id=str(run["id"]), created_at=started))


def _worker_loop(
    *, database: Database, settings: Settings, telemetry: ForgeTelemetry, stop: threading.Event
) -> int:
    queue = InMemoryQueue()
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    consumer = WorkerConsumer(
        database=database,
        queue=queue,
        worker_id=settings.worker_id,
        lease_seconds=settings.task_lease_seconds,
        retry_policy=RetryPolicy(max_attempts=settings.task_max_attempts),
        telemetry=telemetry,
    )
    ticks = 0
    while not stop.is_set():
        dispatcher.dispatch_once()
        consumer.consume_once(block_ms=50)
        ticks += 1
    return ticks


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(pct * (len(ordered) - 1))))
    return ordered[index]


def _await_completion(
    *, database: Database, result: LoadResult, expected: int, timeout_seconds: float
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with result.lock:
            pending = [t for t in result.timings if t.completed_at is None]
            run_ids = [t.run_id for t in pending]
        if not run_ids:
            if len(result.timings) >= expected:
                return
            time.sleep(0.05)
            continue
        with database.transaction(tenant_id=TENANT_ID) as conn:
            rows = conn.execute(
                "select id, status from runs where id = any(%s)",
                (run_ids,),
            ).fetchall()
        terminal = {
            str(row["id"]) for row in rows if row["status"] in {"succeeded", "failed", "cancelled"}
        }
        if terminal:
            now = time.monotonic()
            with result.lock:
                for timing in result.timings:
                    if timing.run_id in terminal and timing.completed_at is None:
                        timing.completed_at = now
        with result.lock:
            if len(result.timings) >= expected and all(
                t.completed_at is not None for t in result.timings
            ):
                return
        time.sleep(0.1)


def run_load_drill(database: Database, settings: Settings) -> dict[str, Any]:
    actor = _actor(database, settings)
    with database.transaction(actor_id=actor.user_id) as conn:
        workflow = next(
            v
            for v in WorkflowRepository(conn).list_versions_for_actor(actor_id=actor.user_id)
            if v["name"] == "Incident Response Demo"
        )

    telemetry = ForgeTelemetry(settings=settings)
    result = LoadResult()
    stop = threading.Event()

    worker_threads = [
        threading.Thread(
            target=_worker_loop,
            kwargs={
                "database": database,
                "settings": settings,
                "telemetry": telemetry,
                "stop": stop,
            },
        )
        for _ in range(WORKER_COUNT)
    ]
    for thread in worker_threads:
        thread.start()

    run_service = RunService(database, telemetry=telemetry)
    start = time.monotonic()
    _create_runs(
        run_service=run_service,
        actor=actor,
        workflow_version_id=str(workflow["id"]),
        workspace_id=str(workflow["workspace_id"]),
        count=RUN_COUNT,
        result=result,
    )
    creation_elapsed = time.monotonic() - start

    _await_completion(
        database=database, result=result, expected=RUN_COUNT, timeout_seconds=SOAK_SECONDS
    )
    total_elapsed = time.monotonic() - start
    stop.set()
    for thread in worker_threads:
        thread.join(timeout=5)
    telemetry.shutdown()

    completed = [t for t in result.timings if t.completed_at is not None]
    latencies = [t.completed_at - t.created_at for t in completed if t.completed_at is not None]
    tasks_per_run = 4  # Incident Response Demo: 4 deterministic steps, no approvals/tools

    report = {
        "profile": "local_single_machine_no_connection_pool",
        "run_count_requested": RUN_COUNT,
        "run_count_completed": len(completed),
        "worker_thread_count": WORKER_COUNT,
        "run_creation_seconds": round(creation_elapsed, 3),
        "run_creation_throughput_runs_per_sec": (
            round(RUN_COUNT / creation_elapsed, 2) if creation_elapsed > 0 else 0
        ),
        "total_wall_clock_seconds": round(total_elapsed, 3),
        "end_to_end_throughput_runs_per_sec": (
            round(len(completed) / total_elapsed, 2) if total_elapsed > 0 else 0
        ),
        "estimated_tasks_completed": len(completed) * tasks_per_run,
        "estimated_task_throughput_per_sec": (
            round((len(completed) * tasks_per_run) / total_elapsed, 2) if total_elapsed > 0 else 0
        ),
        "run_latency_seconds": {
            "p50": round(_percentile(latencies, 0.50), 3),
            "p95": round(_percentile(latencies, 0.95), 3),
            "p99": round(_percentile(latencies, 0.99), 3),
            "max": round(max(latencies), 3) if latencies else 0,
            "mean": round(statistics.fmean(latencies), 3) if latencies else 0,
        },
        "modeled_100x_extrapolation": {
            "method": "naive linear scaling of measured single-machine throughput; NOT validated",
            "caveat": (
                "Real capacity at 100x load depends on Postgres connection limits (no pool "
                "exists today — every transaction opens a fresh connection), Redis stream "
                "consumer-group fanout, and horizontal worker scaling, none of which this "
                "single-machine drill exercises. Use this only as a starting order-of-"
                "magnitude estimate, not a capacity guarantee."
            ),
            "modeled_runs_per_sec_at_100x_workers_and_db": (
                round(len(completed) / total_elapsed * 100, 1) if total_elapsed > 0 else 0
            ),
        },
        "paid_provider_calls": 0,
    }
    return report


def main() -> None:
    settings = Settings()
    settings.assert_zero_cost_safe()
    _assert_local_url(settings.database_url, label="FORGE_DATABASE_URL")
    _assert_local_url(settings.migration_database_url, label="FORGE_MIGRATION_DATABASE_URL")
    _assert_local_url(settings.redis_url, label="FORGE_REDIS_URL")
    seed_main()
    Redis.from_url(settings.redis_url, decode_responses=True).delete(settings.queue_stream)
    database = Database(settings.database_url)

    report = run_load_drill(database, settings)
    _print("phase13_capacity_report", report)


if __name__ == "__main__":
    main()
