import json
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from conftest import auth_headers
from fastapi.testclient import TestClient

from forge_api.application.reliability_service import OutboxDispatcher, WorkerConsumer
from forge_api.config import Settings
from forge_api.domain.reliability import RetryPolicy
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.dev_issuer import DevIssuer
from forge_api.infrastructure.queue import InMemoryQueue
from forge_api.infrastructure.telemetry import (
    ForgeTelemetry,
    NullTelemetry,
    trace_id_as_correlation_uuid,
)


def _headers(issuer: DevIssuer, subject: str = "alice") -> dict[str, str]:
    return auth_headers(issuer, subject)


def _workflow_by_name(client: TestClient, issuer: DevIssuer, name: str) -> Mapping[str, Any]:
    workflows = client.get("/v1/workflows", headers=_headers(issuer)).json()["workflow_versions"]
    return next(workflow for workflow in workflows if workflow["name"] == name)


def _create_run(
    client: TestClient, issuer: DevIssuer, workflow: Mapping[str, Any]
) -> Mapping[str, Any]:
    response = client.post(
        "/v1/runs",
        headers=_headers(issuer) | {"Idempotency-Key": f"phase13-telemetry-run-{uuid4()}"},
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Exercise Phase 13 OTel trace propagation across the async path.",
        },
    )
    assert response.status_code == 201
    run: Mapping[str, Any] = response.json()["run"]
    return run


def _run_worker_until_terminal(
    *, database: Database, settings: Settings, client: TestClient, issuer: DevIssuer, run_id: str
) -> Mapping[str, Any]:
    queue = InMemoryQueue()
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    consumer = WorkerConsumer(
        database=database,
        queue=queue,
        worker_id=settings.worker_id,
        lease_seconds=settings.task_lease_seconds,
        retry_policy=RetryPolicy(max_attempts=settings.task_max_attempts),
        telemetry=ForgeTelemetry(settings=settings),
    )
    run: Mapping[str, Any] = {}
    for _ in range(80):
        dispatcher.dispatch_once()
        outcome = consumer.consume_once(block_ms=0)
        if outcome == "waiting_approval":
            pending = client.get(
                "/v1/approvals", headers=_headers(issuer, "ava")
            ).json()["approval_requests"]
            for approval in pending:
                if approval["status"] != "pending":
                    continue
                client.post(
                    f"/v1/approvals/{approval['id']}:approve",
                    headers=_headers(issuer, "ava")
                    | {
                        "Idempotency-Key": f"phase13-telemetry-approve-{uuid4()}",
                        "If-Match": str(approval["request_version"]),
                    },
                    json={"reason": "Exercising Phase 13 trace propagation."},
                )
        run = client.get(f"/v1/runs/{run_id}", headers=_headers(issuer)).json()["run"]
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            return run
    raise AssertionError("run did not become terminal")


def _read_spans(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_span_yields_a_valid_w3c_traceparent(tmp_path: Path) -> None:
    settings = Settings(telemetry_local_export_path=tmp_path / "spans.jsonl")
    telemetry = ForgeTelemetry(settings=settings)
    with telemetry.span("unit.test") as carrier:
        traceparent = carrier["traceparent"]
    parts = traceparent.split("-")
    assert len(parts) == 4
    assert len(parts[1]) == 32
    assert len(parts[2]) == 16
    telemetry.shutdown()


def test_local_exporter_redacts_secret_and_token_attributes(tmp_path: Path) -> None:
    path = tmp_path / "spans.jsonl"
    settings = Settings(telemetry_local_export_path=path)
    telemetry = ForgeTelemetry(settings=settings)
    with telemetry.span(
        "unit.redaction", attributes={"api_token": "sk-live-secret", "safe_field": "ok"}  # noqa: S106
    ):
        pass
    telemetry.shutdown()
    spans = _read_spans(path)
    assert len(spans) == 1
    assert spans[0]["attributes"]["api_token"] == "[redacted]"  # noqa: S105
    assert spans[0]["attributes"]["safe_field"] == "ok"


def test_exporter_failure_never_blocks_the_wrapped_operation() -> None:
    with tempfile.TemporaryDirectory() as blocked_dir:
        blocked_parent = Path(blocked_dir) / "no-such-parent"
        blocked_parent.mkdir()
        blocked_parent.chmod(0o400)
        try:
            settings = Settings(
                telemetry_local_export_path=blocked_parent / "child" / "spans.jsonl"
            )
            telemetry = ForgeTelemetry(settings=settings)
            work_happened = False
            with telemetry.span("unit.exporter_outage"):
                work_happened = True
            telemetry.shutdown()
            assert work_happened
        finally:
            blocked_parent.chmod(0o700)


def test_null_telemetry_is_a_safe_default() -> None:
    telemetry = NullTelemetry()
    with telemetry.span("noop") as carrier:
        assert carrier == {}
    telemetry.record_exception(RuntimeError("no-op"))


def test_trace_id_as_correlation_uuid_round_trips_the_hex_trace_id() -> None:
    trace_id_hex = "1ed25918adbba8fe55248b3b5eb4f0b6"
    correlation_id = trace_id_as_correlation_uuid(int(trace_id_hex, 16))
    assert UUID(correlation_id).hex == trace_id_hex


def test_run_create_and_worker_task_share_one_trace_across_the_async_path(
    database: Database, settings: Settings, client: TestClient, issuer: DevIssuer
) -> None:
    workflow = _workflow_by_name(client, issuer, "Typed Tool Demo")
    run = _create_run(client, issuer, workflow)

    completed = _run_worker_until_terminal(
        database=database, settings=settings, client=client, issuer=issuer, run_id=str(run["id"])
    )
    assert completed["status"] == "succeeded"

    with database.transaction(worker_id=settings.worker_id) as conn:
        correlated = conn.execute(
            """
            select t.step_key, e.correlation_id, e.trace_context
            from execution_events e
            join tasks t on t.id = e.task_id
            where e.run_id = %s and e.event_type = 'task.trace_correlated'
            order by e.sequence
            """,
            (run["id"],),
        ).fetchall()
    # simulated_ticket needs approval, so it is attempted twice (suspend,
    # then resume after Ava approves) and gets a "task.trace_correlated"
    # event per attempt; the two parallel root tasks need only one each.
    assert len(correlated) == 4
    first_by_step: dict[str, Any] = {}
    for row in correlated:
        first_by_step.setdefault(str(row["step_key"]), row)

    # deployment_history and customer_reports are ready immediately at run
    # creation, so both inherit the run.create span's root trace. The
    # dependent simulated_ticket task becomes ready only later, via the
    # existing task-completion path (not threaded with trace_context in this
    # bounded rollout), so it gets its own fresh trace per attempt.
    root_trace_id_hex = UUID(str(first_by_step["deployment_history"]["correlation_id"])).hex
    assert UUID(str(first_by_step["customer_reports"]["correlation_id"])).hex == root_trace_id_hex
    for step_key in ("deployment_history", "customer_reports"):
        traceparent = first_by_step[step_key]["trace_context"]["traceparent"]
        assert traceparent.split("-")[1] == root_trace_id_hex

    spans = _read_spans(settings.telemetry_local_export_path)
    trace_ids_by_name: dict[str, set[str]] = {}
    for span in spans:
        trace_ids_by_name.setdefault(span["name"], set()).add(span["trace_id"])
    assert root_trace_id_hex in trace_ids_by_name.get("run.create", set())
    assert root_trace_id_hex in trace_ids_by_name.get("task.execute", set())
