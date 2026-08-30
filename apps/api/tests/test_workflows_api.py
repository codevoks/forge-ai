import json
from collections.abc import Mapping
from typing import Any

from conftest import auth_headers
from fastapi.testclient import TestClient

from forge_api.infrastructure.dev_issuer import DevIssuer


def stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def headers(issuer: DevIssuer, subject: str, key: str | None = None) -> dict[str, str]:
    base = auth_headers(issuer, subject)
    if key:
        base["Idempotency-Key"] = key
    return base


def seeded_workspace_id(client: TestClient, issuer: DevIssuer) -> str:
    return str(seeded_workflow(client, issuer)["workspace_id"])


def seeded_workflow(client: TestClient, issuer: DevIssuer) -> Mapping[str, Any]:
    workflows = client.get("/v1/workflows", headers=headers(issuer, "alice")).json()
    return next(
        workflow
        for workflow in workflows["workflow_versions"]
        if workflow["name"] == "Incident Response Demo"
    )


def seeded_workflow_id(client: TestClient, issuer: DevIssuer) -> str:
    return str(seeded_workflow(client, issuer)["id"])


def create_run(client: TestClient, issuer: DevIssuer, key: str) -> Mapping[str, Any]:
    response = client.post(
        "/v1/runs",
        headers=headers(issuer, "alice", key),
        json={
            "workspace_id": seeded_workspace_id(client, issuer),
            "workflow_version_id": seeded_workflow_id(client, issuer),
            "objective": "Investigate the deterministic demo incident.",
        },
    )
    assert response.status_code == 201
    return response.json()["run"]


def test_seeded_workflow_is_listed_with_dag(client: TestClient, issuer: DevIssuer) -> None:
    response = client.get("/v1/workflows", headers=headers(issuer, "alice"))

    assert response.status_code == 200
    workflow = next(
        workflow
        for workflow in response.json()["workflow_versions"]
        if workflow["name"] == "Incident Response Demo"
    )
    assert workflow["name"] == "Incident Response Demo"
    assert [step["key"] for step in workflow["steps"]] == [
        "collect_logs",
        "correlate",
        "inspect_metrics",
        "summarize",
    ]
    assert {"from": "collect_logs", "to": "correlate"} in workflow["edges"]


def test_run_creation_instantiates_ready_root_tasks(client: TestClient, issuer: DevIssuer) -> None:
    run = create_run(client, issuer, "run-create-roots")
    tasks = client.get(f"/v1/runs/{run['id']}/tasks", headers=headers(issuer, "alice")).json()[
        "tasks"
    ]

    assert run["status"] == "running"
    assert {task["step_key"]: task["status"] for task in tasks} == {
        "collect_logs": "ready",
        "inspect_metrics": "ready",
        "correlate": "pending",
        "summarize": "pending",
    }


def test_deterministic_advance_completes_full_dag(client: TestClient, issuer: DevIssuer) -> None:
    run = create_run(client, issuer, "run-create-full-dag")

    statuses: list[str] = []
    for _ in range(4):
        response = client.post(f"/v1/runs/{run['id']}:advance", headers=headers(issuer, "alice"))
        assert response.status_code == 200
        statuses.append(response.json()["run"]["status"])

    assert statuses[-1] == "succeeded"
    tasks = client.get(f"/v1/runs/{run['id']}/tasks", headers=headers(issuer, "alice")).json()[
        "tasks"
    ]
    assert {task["status"] for task in tasks} == {"succeeded"}
    events = client.get(f"/v1/runs/{run['id']}/events", headers=headers(issuer, "alice")).json()[
        "events"
    ]
    event_types = [event["event_type"] for event in events]
    assert event_types.count("task.ready") == 4
    assert event_types.count("task.succeeded") == 4
    assert event_types[-1] == "run.succeeded"


def test_run_create_is_idempotent(client: TestClient, issuer: DevIssuer) -> None:
    payload = {
        "workspace_id": seeded_workspace_id(client, issuer),
        "workflow_version_id": seeded_workflow_id(client, issuer),
        "objective": "Create one idempotent run.",
    }
    request_headers = headers(issuer, "alice", "run-create-idempotent")

    first = client.post("/v1/runs", headers=request_headers, json=payload)
    second = client.post("/v1/runs", headers=request_headers, json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert stable(first.json()) == stable(second.json())


def test_invalid_cyclic_workflow_is_rejected(client: TestClient, issuer: DevIssuer) -> None:
    response = client.post(
        "/v1/workflows",
        headers=headers(issuer, "alice", "workflow-cycle"),
        json={
            "workspace_id": seeded_workspace_id(client, issuer),
            "name": "Invalid Cycle",
            "steps": [
                {"key": "a", "name": "Step A", "kind": "deterministic"},
                {"key": "b", "name": "Step B", "kind": "deterministic"},
            ],
            "edges": [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}],
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "workflow_cycle"
