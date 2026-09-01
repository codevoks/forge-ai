from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from forge_api.application.reliability_service import OutboxDispatcher, WorkerConsumer
from forge_api.config import Settings
from forge_api.domain.reliability import RetryPolicy
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.dev_issuer import DevIssuer
from forge_api.infrastructure.queue import InMemoryQueue
from forge_api.main import create_app
from forge_api.scripts.seed import main as seed_main


def _headers(issuer: DevIssuer, subject: str = "alice", key: str | None = None) -> dict[str, str]:
    subjects = {
        "alice": ("oidc|alice", "alice@forge.local", "Alice Admin"),
        "bob": ("oidc|bob", "bob@forge.local", "Bob Viewer"),
        "mallory": ("oidc|mallory", "mallory@forge.local", "Mallory Outsider"),
    }
    sub, email, name = subjects[subject]
    token = issuer.token_for_subject(subject=sub, email=email, name=name)
    request_headers = {"Authorization": f"Bearer {token}"}
    if key:
        request_headers["Idempotency-Key"] = key
    return request_headers


def _workflow_by_name(client: TestClient, issuer: DevIssuer, name: str) -> dict[str, Any]:
    response = client.get("/v1/workflows", headers=_headers(issuer))
    response.raise_for_status()
    return next(
        workflow for workflow in response.json()["workflow_versions"] if workflow["name"] == name
    )


def _create_langgraph_run(client: TestClient, issuer: DevIssuer) -> dict[str, Any]:
    workflow = _workflow_by_name(client, issuer, "Bounded Agent Demo")
    response = client.post(
        "/v1/runs",
        headers=_headers(issuer, key=f"debugger-demo-run-{uuid4()}"),
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Demonstrate execution history, debugging, replay, and trace export.",
            "engine_kind": "langgraph",
        },
    )
    response.raise_for_status()
    run = response.json()["run"]
    assert isinstance(run, dict)
    return run


def _drive_run(
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
    outcomes: list[str] = []
    for _ in range(20):
        dispatcher.dispatch_once()
        outcomes.append(consumer.consume_once(block_ms=0))
        run = client.get(f"/v1/runs/{run_id}", headers=_headers(issuer)).json()["run"]
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            run["worker_outcomes"] = outcomes
            assert isinstance(run, dict)
            return run
    raise RuntimeError("Debugger demo run did not terminate.")


def main() -> None:
    settings = Settings()
    settings.assert_zero_cost_safe()
    seed_main()
    client = TestClient(create_app())
    database = Database(settings.database_url)
    issuer = DevIssuer(settings.oidc_issuer, settings.oidc_audience, settings.oidc_jwks_path)

    print("Forge execution debugger and safe replay demo")

    run = _create_langgraph_run(client, issuer)
    completed_run = _drive_run(
        client=client,
        issuer=issuer,
        database=database,
        settings=settings,
        run_id=str(run["id"]),
    )
    print(
        {
            "completed_execution": {
                "run_id": completed_run["id"],
                "status": completed_run["status"],
                "engine": completed_run["engine_kind"],
                "worker_outcomes": completed_run["worker_outcomes"],
            }
        }
    )

    debugger_response = client.get(
        f"/v1/runs/{run['id']}/debugger",
        headers=_headers(issuer),
    )
    debugger_response.raise_for_status()
    debugger = debugger_response.json()["debugger"]
    print(
        {
            "debugger_snapshot": {
                "events": len(debugger["timeline"]["events"]),
                "event_schema_versions": sorted(
                    {event["schema_version"] for event in debugger["timeline"]["events"]}
                ),
                "model_calls": len(debugger["model_calls"]),
                "tool_invocations": len(debugger["tool_invocations"]),
                "agent_iterations": len(debugger["agent_iterations"]),
                "forge_checkpoints": len(debugger["forge_checkpoints"]),
                "langgraph_checkpoints": len(debugger["engine_checkpoints"]),
                "raw_payloads_exposed": debugger["security_posture"]["raw_payloads_exposed"],
                "framework_state_authoritative": debugger["security_posture"][
                    "framework_state_authoritative"
                ],
            }
        }
    )

    first_page = client.get(
        f"/v1/runs/{run['id']}/debugger/events",
        headers=_headers(issuer),
        params={"limit": 2},
    )
    first_page.raise_for_status()
    first_timeline = first_page.json()["timeline"]
    second_page = client.get(
        f"/v1/runs/{run['id']}/debugger/events",
        headers=_headers(issuer),
        params={"cursor": first_timeline["next_cursor"], "limit": 10},
    )
    second_page.raise_for_status()
    print(
        {
            "cursor_resume": {
                "first_sequences": [
                    event["sequence"] for event in first_timeline["events"]
                ],
                "second_sequences": [
                    event["sequence"] for event in second_page.json()["timeline"]["events"]
                ],
            }
        }
    )

    projection = client.post(
        f"/v1/runs/{run['id']}/debugger/projection-verifications",
        headers=_headers(issuer, key=f"debugger-demo-projection-{uuid4()}"),
    )
    projection.raise_for_status()
    print(
        {
            "projection_verification": projection.json()["projection_verification"],
        }
    )

    replay = client.post(
        f"/v1/runs/{run['id']}/debugger/replays",
        headers=_headers(issuer, key=f"debugger-demo-replay-{uuid4()}"),
        json={"mode": "simulation"},
    )
    replay.raise_for_status()
    replay_session = replay.json()["replay_session"]
    print(
        {
            "simulation_replay": {
                "status": replay_session["status"],
                "summary": replay_session["summary"],
                "tripwire": replay_session["artifacts"][0]["payload"]["tripwire"],
            }
        }
    )

    unsafe_replay = client.post(
        f"/v1/runs/{run['id']}/debugger/replays",
        headers=_headers(issuer, key=f"debugger-demo-unsafe-replay-{uuid4()}"),
        json={"mode": "effect_replay"},
    )
    unsafe_replay.raise_for_status()
    unsafe_session = unsafe_replay.json()["replay_session"]
    print(
        {
            "unsafe_effect_replay": {
                "status": unsafe_session["status"],
                "reason": unsafe_session["summary"]["reason"],
                "approval_reused": unsafe_session["policy"]["reuses_approval"],
                "authoritative_state_mutated": unsafe_session["summary"][
                    "authoritative_state_mutated"
                ],
            }
        }
    )

    trace_export = client.post(
        f"/v1/runs/{run['id']}/debugger/trace-exports",
        headers=_headers(issuer, key=f"debugger-demo-trace-export-{uuid4()}"),
        json={"exporter": "langsmith", "mode": "local"},
    )
    trace_export.raise_for_status()
    export = trace_export.json()["trace_export"]
    print(
        {
            "local_trace_export": {
                "status": export["status"],
                "live_export": export["live_export"],
                "paid_provider_calls": export["artifact"]["paid_provider_calls"],
                "event_refs": len(export["artifact"]["event_refs"]),
                "model_call_refs": len(export["artifact"]["model_call_refs"]),
                "tool_invocation_refs": len(export["artifact"]["tool_invocation_refs"]),
                "langgraph_checkpoint_refs": len(export["artifact"]["langgraph_checkpoint_refs"]),
            }
        }
    )

    live_export = client.post(
        f"/v1/runs/{run['id']}/debugger/trace-exports",
        headers=_headers(issuer, key=f"debugger-demo-live-export-{uuid4()}"),
        json={"exporter": "langsmith", "mode": "enabled"},
    )
    live_export.raise_for_status()
    live = live_export.json()["trace_export"]
    print(
        {
            "live_langsmith_without_opt_in": {
                "status": live["status"],
                "live_export": live["live_export"],
                "reason": live["artifact"]["reason"],
                "external_integrations": settings.external_integrations,
            }
        }
    )

    mallory = client.get(
        f"/v1/runs/{run['id']}/debugger",
        headers=_headers(issuer, "mallory"),
    )
    print({"cross_tenant_history_access": {"status_code": mallory.status_code}})

    print(
        {
            "zero_cost": {
                "external_integrations": settings.external_integrations,
                "model_provider": settings.model_provider,
                "paid_provider_calls": 0,
            }
        }
    )


if __name__ == "__main__":
    main()
