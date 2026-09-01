from typing import Any
from uuid import uuid4

import pytest
from adversarial_cases import DEBUGGER_ADVERSARIAL_CASES
from conftest import auth_headers
from fastapi.testclient import TestClient

from forge_api.application.reliability_service import OutboxDispatcher, WorkerConsumer
from forge_api.config import Settings
from forge_api.domain.reliability import RetryPolicy
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.dev_issuer import DevIssuer
from forge_api.infrastructure.queue import InMemoryQueue


def headers(issuer: DevIssuer, subject: str = "alice", key: str | None = None) -> dict[str, str]:
    request_headers = auth_headers(issuer, subject)
    if key is not None:
        request_headers["Idempotency-Key"] = key
    return request_headers


def workflow_by_name(client: TestClient, issuer: DevIssuer, name: str) -> dict[str, Any]:
    workflows = client.get("/v1/workflows", headers=headers(issuer)).json()["workflow_versions"]
    return next(workflow for workflow in workflows if workflow["name"] == name)


def create_run(
    client: TestClient,
    issuer: DevIssuer,
    *,
    workflow_name: str = "Bounded Agent Demo",
    engine_kind: str = "langgraph",
) -> dict[str, Any]:
    workflow = workflow_by_name(client, issuer, workflow_name)
    response = client.post(
        "/v1/runs",
        headers=headers(issuer, key=f"debug-run-{uuid4()}"),
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Debug a completed local Forge execution.",
            "engine_kind": engine_kind,
        },
    )
    assert response.status_code == 201
    return response.json()["run"]


def drive_run_to_terminal(
    *,
    client: TestClient,
    issuer: DevIssuer,
    database: Database,
    settings: Settings,
    run_id: str,
) -> dict[str, Any]:
    queue = InMemoryQueue()
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    consumer = WorkerConsumer(
        database=database,
        queue=queue,
        worker_id=settings.worker_id,
        lease_seconds=settings.task_lease_seconds,
        retry_policy=RetryPolicy(max_attempts=settings.task_max_attempts),
    )
    for _ in range(20):
        dispatcher.dispatch_once()
        consumer.consume_once(block_ms=0)
        run = client.get(f"/v1/runs/{run_id}", headers=headers(issuer)).json()["run"]
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            return run
    raise AssertionError("Run did not terminate.")


def completed_langgraph_run(
    client: TestClient,
    issuer: DevIssuer,
    database: Database,
    settings: Settings,
) -> dict[str, Any]:
    run = create_run(client, issuer)
    return drive_run_to_terminal(
        client=client,
        issuer=issuer,
        database=database,
        settings=settings,
        run_id=str(run["id"]),
    )


def test_debugger_exposes_sanitized_execution_history_and_framework_evidence(
    client: TestClient,
    issuer: DevIssuer,
    database: Database,
    settings: Settings,
) -> None:
    run = completed_langgraph_run(client, issuer, database, settings)

    response = client.get(f"/v1/runs/{run['id']}/debugger", headers=headers(issuer))

    assert response.status_code == 200
    debugger = response.json()["debugger"]
    assert debugger["run"]["status"] == "succeeded"
    assert debugger["security_posture"]["raw_payloads_exposed"] is False
    assert debugger["security_posture"]["effect_replay_enabled"] is False
    assert debugger["event_catalog"]
    assert debugger["timeline"]["events"]
    assert all(event["schema_version"] == 1 for event in debugger["timeline"]["events"])
    assert all("payload_hash" in event for event in debugger["timeline"]["events"])
    assert debugger["model_calls"]
    assert all(call["live_provider"] is False for call in debugger["model_calls"])
    assert debugger["tool_invocations"]
    assert debugger["agent_iterations"]
    assert debugger["engine_checkpoints"]
    assert "secret-value" not in str(debugger).lower()


def test_debug_event_cursor_resumes_without_duplicates(
    client: TestClient,
    issuer: DevIssuer,
    database: Database,
    settings: Settings,
) -> None:
    run = completed_langgraph_run(client, issuer, database, settings)

    first = client.get(
        f"/v1/runs/{run['id']}/debugger/events?limit=2",
        headers=headers(issuer),
    )
    assert first.status_code == 200
    first_body = first.json()["timeline"]
    second = client.get(
        f"/v1/runs/{run['id']}/debugger/events",
        headers=headers(issuer),
        params={"cursor": first_body["next_cursor"], "limit": 20},
    )

    assert second.status_code == 200
    first_ids = {event["id"] for event in first_body["events"]}
    second_ids = {event["id"] for event in second.json()["timeline"]["events"]}
    assert first_ids.isdisjoint(second_ids)


def test_projection_verifier_passes_for_current_authoritative_state(
    client: TestClient,
    issuer: DevIssuer,
    database: Database,
    settings: Settings,
) -> None:
    run = completed_langgraph_run(client, issuer, database, settings)

    response = client.post(
        f"/v1/runs/{run['id']}/debugger/projection-verifications",
        headers=headers(issuer, key=f"projection-{uuid4()}"),
    )

    assert response.status_code == 201
    verification = response.json()["projection_verification"]
    assert verification["status"] == "passed"
    assert verification["actual_run_status"] == "succeeded"
    assert verification["mismatch_count"] == 0


def test_simulation_replay_persists_tripwire_without_mutating_authoritative_state(
    client: TestClient,
    issuer: DevIssuer,
    database: Database,
    settings: Settings,
) -> None:
    run = completed_langgraph_run(client, issuer, database, settings)
    before = client.get(f"/v1/runs/{run['id']}", headers=headers(issuer)).json()["run"]

    response = client.post(
        f"/v1/runs/{run['id']}/debugger/replays",
        headers=headers(issuer, key=f"replay-{uuid4()}"),
        json={"mode": "simulation"},
    )
    after = client.get(f"/v1/runs/{run['id']}", headers=headers(issuer)).json()["run"]

    assert response.status_code == 201
    replay = response.json()["replay_session"]
    assert replay["mode"] == "simulation"
    assert replay["status"] == "passed"
    assert replay["summary"]["authoritative_state_mutated"] is False
    assert replay["summary"]["paid_provider_calls"] == 0
    assert replay["artifacts"][0]["payload"]["tripwire"]["real_effect_adapter_called"] is False
    assert after["status"] == before["status"]
    assert after["version"] == before["version"]


@pytest.mark.security
def test_effect_replay_is_blocked_and_cannot_reuse_prior_approval(
    client: TestClient,
    issuer: DevIssuer,
    database: Database,
    settings: Settings,
) -> None:
    run = completed_langgraph_run(client, issuer, database, settings)

    response = client.post(
        f"/v1/runs/{run['id']}/debugger/replays",
        headers=headers(issuer, key=f"unsafe-replay-{uuid4()}"),
        json={"mode": "effect_replay"},
    )

    assert response.status_code == 201
    replay = response.json()["replay_session"]
    assert replay["status"] == "blocked"
    assert replay["summary"]["reason"] == "effect_replay_disabled"
    assert replay["policy"]["reuses_approval"] is False
    assert replay["artifacts"][0]["payload"]["tripwire"]["approval_reused"] is False
    assert replay["artifacts"][0]["payload"]["tripwire"]["authoritative_state_mutated"] is False


@pytest.mark.security
def test_debugger_blocks_cross_tenant_history_access(
    client: TestClient,
    issuer: DevIssuer,
    database: Database,
    settings: Settings,
) -> None:
    run = completed_langgraph_run(client, issuer, database, settings)

    response = client.get(f"/v1/runs/{run['id']}/debugger", headers=headers(issuer, "mallory"))

    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"


@pytest.mark.security
def test_viewer_can_inspect_sanitized_history_but_cannot_create_replay_artifacts(
    client: TestClient,
    issuer: DevIssuer,
    database: Database,
    settings: Settings,
) -> None:
    run = completed_langgraph_run(client, issuer, database, settings)

    read = client.get(f"/v1/runs/{run['id']}/debugger", headers=headers(issuer, "bob"))
    replay = client.post(
        f"/v1/runs/{run['id']}/debugger/replays",
        headers=headers(issuer, "bob", key=f"viewer-replay-{uuid4()}"),
        json={"mode": "simulation"},
    )

    assert read.status_code == 200
    assert replay.status_code == 403
    assert replay.json()["code"] == "replay_forbidden"


@pytest.mark.security
def test_forged_debug_cursor_is_rejected(
    client: TestClient,
    issuer: DevIssuer,
    database: Database,
    settings: Settings,
) -> None:
    run = completed_langgraph_run(client, issuer, database, settings)

    response = client.get(
        f"/v1/runs/{run['id']}/debugger/events",
        headers=headers(issuer),
        params={"cursor": "forged"},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "debug_cursor_invalid"


def test_local_trace_export_correlates_events_models_tools_and_checkpoints(
    client: TestClient,
    issuer: DevIssuer,
    database: Database,
    settings: Settings,
) -> None:
    run = completed_langgraph_run(client, issuer, database, settings)

    response = client.post(
        f"/v1/runs/{run['id']}/debugger/trace-exports",
        headers=headers(issuer, key=f"trace-export-{uuid4()}"),
        json={"exporter": "langsmith", "mode": "local"},
    )

    assert response.status_code == 201
    trace_export = response.json()["trace_export"]
    assert trace_export["exporter"] == "langsmith"
    assert trace_export["status"] == "local_artifact"
    assert trace_export["live_export"] is False
    artifact = trace_export["artifact"]
    assert artifact["paid_provider_calls"] == 0
    assert artifact["event_refs"]
    assert artifact["model_call_refs"]
    assert artifact["tool_invocation_refs"]
    assert artifact["langgraph_checkpoint_refs"]


@pytest.mark.security
def test_live_trace_export_fails_closed_without_external_opt_in(
    client: TestClient,
    issuer: DevIssuer,
    database: Database,
    settings: Settings,
) -> None:
    run = completed_langgraph_run(client, issuer, database, settings)

    response = client.post(
        f"/v1/runs/{run['id']}/debugger/trace-exports",
        headers=headers(issuer, key=f"live-trace-export-{uuid4()}"),
        json={"exporter": "langsmith", "mode": "enabled"},
    )

    assert response.status_code == 201
    trace_export = response.json()["trace_export"]
    assert trace_export["status"] == "blocked"
    assert trace_export["live_export"] is False
    assert trace_export["artifact"]["reason"] == "external_integrations_disabled"


@pytest.mark.security
def test_debugger_adversarial_corpus_tracks_phase_10_attack_surfaces() -> None:
    cases = {case.scenario: case for case in DEBUGGER_ADVERSARIAL_CASES}

    assert cases["effect_replay"].expected_outcome == "blocked"
    assert cases["forged_cursor"].expected_outcome == "denied"
    assert cases["cross_tenant_history"].expected_outcome == "denied"
