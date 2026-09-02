import signal
import time

from forge_api.application.reliability_service import (
    OutboxDispatcher,
    RecoveryService,
    WorkerConsumer,
)
from forge_api.config import Settings
from forge_api.domain.reliability import RetryPolicy
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.queue import RedisStreamQueue
from forge_api.infrastructure.telemetry import ForgeTelemetry


def health() -> dict[str, str]:
    settings = Settings()
    return {
        "status": "ok",
        "service": "worker",
        "execution": "durable-local-queue",
        "external_integrations": settings.external_integrations,
        "queue": settings.queue_stream,
    }


def main() -> None:
    settings = Settings()
    settings.assert_zero_cost_safe()
    database = Database(settings.database_url)
    queue = RedisStreamQueue(
        redis_url=settings.redis_url,
        stream_name=settings.queue_stream,
        group_name=settings.queue_group,
    )
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    telemetry = ForgeTelemetry(settings=settings)
    consumer = WorkerConsumer(
        database=database,
        queue=queue,
        worker_id=settings.worker_id,
        lease_seconds=settings.task_lease_seconds,
        retry_policy=RetryPolicy(max_attempts=settings.task_max_attempts),
        telemetry=telemetry,
    )
    recovery = RecoveryService(database=database, worker_id=settings.worker_id)
    should_stop = False

    def request_shutdown(signum: int, frame: object) -> None:
        _ = signum
        _ = frame
        nonlocal should_stop
        should_stop = True

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)

    print(health(), flush=True)
    while not should_stop:
        recovered = recovery.scan_once()
        dispatched = dispatcher.dispatch_once()
        outcome = consumer.consume_once(block_ms=250)
        print(
            {
                "worker": settings.worker_id,
                "recovered": recovered,
                "dispatched": dispatched,
                "outcome": outcome,
            },
            flush=True,
        )
        if outcome == "idle" and dispatched == 0 and not any(recovered.values()):
            time.sleep(settings.worker_tick_seconds)

    telemetry.shutdown()
    print("worker shutdown requested", flush=True)


if __name__ == "__main__":
    main()
