from uuid import uuid4

import pytest
from conftest import auth_headers
from fastapi.testclient import TestClient

from forge_api.api.errors import ProblemError
from forge_api.application.multi_agent_router import apply_router
from forge_api.domain.agent import AgentDecisionType
from forge_api.domain.workflow import DAGValidator, WorkflowEdgeDefinition, WorkflowStepDefinition
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.dev_issuer import DevIssuer
from forge_api.scripts.seed import WORKSPACE_ID

pytestmark = pytest.mark.security


def headers(issuer: DevIssuer, subject: str = "alice", key: str | None = None) -> dict[str, str]:
    request_headers = auth_headers(issuer, subject)
    if key:
        request_headers["Idempotency-Key"] = key
    return request_headers


def multi_agent_workflow(client: TestClient, issuer: DevIssuer) -> dict:
    workflows = client.get("/v1/workflows", headers=headers(issuer)).json()["workflow_versions"]
    return next(w for w in workflows if w["name"] == "Multi-Agent Investigation Demo")


# -- RBAC -------------------------------------------------------------------------


def test_viewer_cannot_create_multi_agent_run(client: TestClient, issuer: DevIssuer) -> None:
    workflow = multi_agent_workflow(client, issuer)
    response = client.post(
        "/v1/runs",
        headers=headers(issuer, "bob", key=f"viewer-multi-{uuid4()}"),
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Investigate deployment and customer impact.",
            "strategy_kind": "multi_agent_parallel",
        },
    )
    assert response.status_code == 403
    assert response.json()["code"] == "run_create_forbidden"


def test_viewer_cannot_trigger_strategy_comparison(client: TestClient, issuer: DevIssuer) -> None:
    response = client.post(
        f"/v1/multi-agent/comparisons?workspace_id={WORKSPACE_ID}",
        headers=headers(issuer, "bob", key=f"viewer-cmp-{uuid4()}"),
    )
    assert response.status_code == 403
    assert response.json()["code"] == "multi_agent_comparison_forbidden"


# -- cross-tenant isolation --------------------------------------------------------


def test_mallory_cannot_read_a_multi_agent_run(client: TestClient, issuer: DevIssuer) -> None:
    workflow = multi_agent_workflow(client, issuer)
    created = client.post(
        "/v1/runs",
        headers=headers(issuer, "alice", key=f"idor-multi-{uuid4()}"),
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Investigate deployment and customer impact.",
            "strategy_kind": "multi_agent_parallel",
        },
    ).json()["run"]

    response = client.get(f"/v1/runs/{created['id']}", headers=headers(issuer, "mallory"))
    assert response.status_code == 404
    assert response.json()["code"] == "run_not_found"


def test_rls_blocks_strategy_comparisons_without_tenant_context(
    database: Database, client: TestClient, issuer: DevIssuer
) -> None:
    response = client.post(
        f"/v1/multi-agent/comparisons?workspace_id={WORKSPACE_ID}",
        headers=headers(issuer, "alice", key=f"rls-cmp-{uuid4()}"),
    )
    assert response.status_code == 201
    with database.transaction() as conn:
        rows = conn.execute("select id from strategy_comparisons").fetchall()
    assert rows == []


# -- forged / unknown role -----------------------------------------------------


def test_workflow_step_with_unknown_agent_role_is_rejected_at_run_creation() -> None:
    workflow_version = {
        "steps": [
            {
                "key": "spec_a",
                "name": "A",
                "kind": "agent",
                "input": {"agent_role": "deployment_specialist"},
            },
            {
                "key": "spec_forged",
                "name": "Forged",
                "kind": "agent",
                "input": {"agent_role": "root_admin_specialist"},
            },
        ],
        "edges": [],
    }
    with pytest.raises(ProblemError) as exc_info:
        apply_router(workflow_version=workflow_version, objective="deploy")
    assert exc_info.value.code == "agent_role_unknown"


def test_comparison_idempotency_key_reuse_replays_the_same_comparison(
    client: TestClient, issuer: DevIssuer
) -> None:
    key = f"cmp-reuse-{uuid4()}"
    url = f"/v1/multi-agent/comparisons?workspace_id={WORKSPACE_ID}"
    first = client.post(url, headers=headers(issuer, key=key))
    assert first.status_code == 201
    second = client.post(url, headers=headers(issuer, key=key))
    assert second.status_code == 201
    first_id = first.json()["strategy_comparison"]["id"]
    second_id = second.json()["strategy_comparison"]["id"]
    assert first_id == second_id


# -- structural prevention of runaway/recursive delegation -----------------------


def test_agent_decision_schema_has_no_spawn_or_delegate_primitive() -> None:
    """A model can never create new agent/task authority: the decision schema
    itself has no delegation primitive, only tool_call/complete/fail/
    request_replan. Unsafe recursive delegation and runaway agent spawning
    are therefore structurally impossible, not merely policy-denied."""
    assert {member.value for member in AgentDecisionType} == {
        "tool_call",
        "complete",
        "fail",
        "request_replan",
    }


def test_cyclic_specialist_dependency_is_rejected_by_the_existing_dag_validator() -> None:
    """Multi-agent workflows reuse the unchanged Phase 2 DAG validator; a
    cyclic dependency between two 'specialists' is rejected exactly like any
    other cyclic workflow, with no special-casing for agent steps."""
    steps = [
        WorkflowStepDefinition(key="spec_a", name="A", kind="agent", input={}),
        WorkflowStepDefinition(key="spec_b", name="B", kind="agent", input={}),
    ]
    edges = [
        WorkflowEdgeDefinition(from_key="spec_a", to_key="spec_b"),
        WorkflowEdgeDefinition(from_key="spec_b", to_key="spec_a"),
    ]
    with pytest.raises(ProblemError) as exc_info:
        DAGValidator().validate(steps=steps, edges=edges)
    assert exc_info.value.code == "workflow_cycle"


def test_max_specialists_bounds_fan_out_width() -> None:
    from forge_api.domain.multi_agent import MAX_SPECIALISTS

    assert MAX_SPECIALISTS <= 4  # matches the workflow DAG's own MAX_STEPS headroom
