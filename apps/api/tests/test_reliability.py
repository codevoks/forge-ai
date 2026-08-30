from collections.abc import Mapping
from typing import Any

from conftest import auth_headers
from fastapi.testclient import TestClient

from forge_api.application.reliability_service import OutboxDispatcher, RetryPolicy, WorkerConsumer
from forge_api.config import Settings
from forge_api.domain.reliability import JobEnvelope
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.dev_issuer import DevIssuer
from forge_api.infrastructure.queue import InMemoryQueue
from forge_api.infrastructure.workflow_repositories import OutboxRepository, WorkerRepository


def headers(issuer: DevIssuer, subject: str = "alice", key: str | None = None) -> dict[str, str]:
    request_headers = auth_headers(issuer, subject)
    if key:
        request_headers["Idempotency-Key"] = key
    return request_headers


def seeded_workflow(client: TestClient, issuer: DevIssuer) -> Mapping[str, Any]:
    workflows = client.get("/v1/workflows", headers=headers(issuer)).json()["workflow_versions"]
    return next(workflow for workflow in workflows if workflow["name"] == "Incident Response Demo")


def publish_workflow(
    client: TestClient,
    issuer: DevIssuer,
    *,
    key: str,
    name: str,
    failure_mode: str | None = None,
) -> Mapping[str, Any]:
    base = seeded_workflow(client, issuer)
    step: dict[str, Any] = {"key": "only", "name": "Only Step", "kind": "deterministic"}
    if failure_mode is not None:
        step["input"] = {"failure_mode": failure_mode}
    response = client.post(
        "/v1/workflows",
        headers=headers(issuer, key=key),
        json={
            "workspace_id": base["workspace_id"],
            "name": name,
            "steps": [step],
            "edges": [],
        },
    )
    assert response.status_code == 201
    return response.json()["workflow_version"]


def create_run(
    client: TestClient,
    issuer: DevIssuer,
    *,
    key: str,
    workflow: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    selected = workflow or seeded_workflow(client, issuer)
    response = client.post(
        "/v1/runs",
        headers=headers(issuer, key=key),
        json={
            "workspace_id": selected["workspace_id"],
            "workflow_version_id": selected["id"],
            "objective": "Exercise Phase 3 durable worker behavior.",
        },
    )
    assert response.status_code == 201
    return response.json()["run"]


def run_worker_until_terminal(
    *,
    database: Database,
    settings: Settings,
    queue: InMemoryQueue,
    client: TestClient,
    issuer: DevIssuer,
    run_id: str,
    max_ticks: int = 20,
) -> Mapping[str, Any]:
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    consumer = WorkerConsumer(
        database=database,
        queue=queue,
        worker_id=settings.worker_id,
        lease_seconds=settings.task_lease_seconds,
        retry_policy=RetryPolicy(max_attempts=settings.task_max_attempts),
    )
    run: Mapping[str, Any] = {}
    for _ in range(max_ticks):
        dispatcher.dispatch_once()
        consumer.consume_once(block_ms=0)
        client.post("/v1/operations/recovery:scan", headers=headers(issuer))
        run = client.get(f"/v1/runs/{run_id}", headers=headers(issuer)).json()["run"]
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            return run
    raise AssertionError("run did not become terminal")


def test_outbox_worker_completes_dag_without_api_advance(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    queue = InMemoryQueue()
    run = create_run(client, issuer, key="phase3-worker-complete")

    completed = run_worker_until_terminal(
        database=database,
        settings=settings,
        queue=queue,
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )

    assert completed["status"] == "succeeded"
    tasks = client.get(f"/v1/runs/{run['id']}/tasks", headers=headers(issuer)).json()["tasks"]
    assert {task["status"] for task in tasks} == {"succeeded"}
    events = client.get(f"/v1/runs/{run['id']}/events", headers=headers(issuer)).json()["events"]
    assert "task.claimed" in [event["event_type"] for event in events]


def test_duplicate_delivery_produces_one_authoritative_outcome(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    queue = InMemoryQueue()
    run = create_run(client, issuer, key="phase3-duplicate-delivery")
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    dispatcher.dispatch_once()
    queue.messages.extend(list(queue.messages))

    completed = run_worker_until_terminal(
        database=database,
        settings=settings,
        queue=queue,
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )

    assert completed["status"] == "succeeded"
    tasks = client.get(f"/v1/runs/{run['id']}/tasks", headers=headers(issuer)).json()["tasks"]
    assert len(tasks) == 4


def test_recovery_republishes_ready_task_after_queue_loss(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    queue = InMemoryQueue()
    run = create_run(client, issuer, key="phase3-redis-loss")
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    assert dispatcher.dispatch_once() == 2
    queue.messages.clear()

    recovery = client.post(
        "/v1/operations/recovery:scan",
        headers=headers(issuer),
    ).json()["recovery"]
    assert recovery["republished_ready_tasks"] == 2
    assert dispatcher.dispatch_once() == 2

    completed = run_worker_until_terminal(
        database=database,
        settings=settings,
        queue=queue,
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )
    assert completed["status"] == "succeeded"


def test_stale_fencing_rejects_expired_lease_commit(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    run = create_run(client, issuer, key="phase3-stale-fencing")
    with database.transaction(worker_id=settings.worker_id) as conn:
        envelope = OutboxRepository(conn).due_unpublished(limit=1)[0]
        claim = WorkerRepository(conn, lease_seconds=-1).claim_task(
            envelope=envelope,
            worker_id=settings.worker_id,
            actor_id=str(envelope.payload["actor_id"]),
        )
        assert claim is not None

    with database.transaction(worker_id=settings.worker_id) as conn:
        completed = WorkerRepository(conn).complete_attempt(
            claim=claim,
            result={"mode": "stale"},
            actor_id=str(claim["actor_id"]),
        )

    assert completed is False
    tasks = client.get(f"/v1/runs/{run['id']}/tasks", headers=headers(issuer)).json()["tasks"]
    assert "running" in {task["status"] for task in tasks}


def test_retry_then_success_with_deterministic_backoff(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    workflow = publish_workflow(
        client,
        issuer,
        key="phase3-fail-once-workflow",
        name="Fail Once Workflow",
        failure_mode="fail_once",
    )
    queue = InMemoryQueue()
    run = create_run(client, issuer, key="phase3-fail-once-run", workflow=workflow)

    completed = run_worker_until_terminal(
        database=database,
        settings=settings,
        queue=queue,
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )

    assert completed["status"] == "succeeded"
    events = client.get(f"/v1/runs/{run['id']}/events", headers=headers(issuer)).json()["events"]
    assert "task.retry_scheduled" in [event["event_type"] for event in events]


def test_permanent_failure_dead_letters_and_fails_run(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    workflow = publish_workflow(
        client,
        issuer,
        key="phase3-dead-letter-workflow",
        name="Dead Letter Workflow",
        failure_mode="always_fail",
    )
    queue = InMemoryQueue()
    run = create_run(client, issuer, key="phase3-dead-letter-run", workflow=workflow)

    completed = run_worker_until_terminal(
        database=database,
        settings=settings,
        queue=queue,
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )

    assert completed["status"] == "failed"
    state = client.get(
        "/v1/operations/worker-state",
        headers=headers(issuer),
    ).json()["worker_state"]
    assert state["dead_letters"] >= 1


def test_operator_can_inspect_and_requeue_sanitized_dead_letter(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    workflow = publish_workflow(
        client,
        issuer,
        key="phase3-requeue-dead-letter-workflow",
        name="Requeue Dead Letter Workflow",
        failure_mode="always_fail",
    )
    queue = InMemoryQueue()
    run = create_run(client, issuer, key="phase3-requeue-dead-letter-run", workflow=workflow)

    completed = run_worker_until_terminal(
        database=database,
        settings=settings,
        queue=queue,
        client=client,
        issuer=issuer,
        run_id=str(run["id"]),
    )
    assert completed["status"] == "failed"

    dead_letters = client.get(
        "/v1/operations/dead-letters", headers=headers(issuer)
    ).json()["dead_letters"]
    selected = next(
        dead_letter for dead_letter in dead_letters if dead_letter["run_id"] == run["id"]
    )
    assert selected["sanitized_payload"]["error_type"] == "permanent"
    assert "input" not in selected["sanitized_payload"]

    requeued = client.post(
        f"/v1/operations/dead-letters/{selected['id']}:requeue",
        headers=headers(issuer),
    )

    assert requeued.status_code == 200
    assert requeued.json()["run"]["status"] == "running"
    events = client.get(f"/v1/runs/{run['id']}/events", headers=headers(issuer)).json()["events"]
    assert "dead_letter.requeued" in [event["event_type"] for event in events]

    duplicate = client.post(
        f"/v1/operations/dead-letters/{selected['id']}:requeue",
        headers=headers(issuer),
    )
    assert duplicate.status_code == 409


def test_cancelled_run_does_not_start_new_work(client: TestClient, issuer: DevIssuer) -> None:
    run = create_run(client, issuer, key="phase3-cancel-run")

    response = client.post(
        f"/v1/runs/{run['id']}:cancel",
        headers=headers(issuer),
        json={"reason": "operator requested cancellation"},
    )

    assert response.status_code == 200
    assert response.json()["run"]["status"] == "cancelled"


def test_queue_envelope_payload_contains_only_durable_ids(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    create_run(client, issuer, key="phase3-envelope-shape")

    with database.transaction(worker_id=settings.worker_id) as conn:
        envelope = OutboxRepository(conn).due_unpublished(limit=1)[0]

    assert isinstance(envelope, JobEnvelope)
    assert set(envelope.payload) == {"actor_id", "run_id", "task_id"}
