from uuid import uuid4

import pytest
from adversarial_cases import EVALUATION_ADVERSARIAL_CASES
from conftest import auth_headers
from fastapi.testclient import TestClient

from forge_api.infrastructure.dev_issuer import DevIssuer
from forge_api.scripts.seed import WORKSPACE_ID

EVALUATION_CASES_BY_KEY = {case.case_key: case for case in EVALUATION_ADVERSARIAL_CASES}


def headers(issuer: DevIssuer, subject: str = "alice", key: str | None = None) -> dict[str, str]:
    request_headers = auth_headers(issuer, subject)
    if key is not None:
        request_headers["Idempotency-Key"] = key
    return request_headers


def run_evaluation(
    client: TestClient,
    issuer: DevIssuer,
    *,
    subject: str = "alice",
    key: str | None = None,
    workspace_id: str = WORKSPACE_ID,
    langsmith_export_mode: str = "local",
) -> object:
    return client.post(
        "/v1/evaluations",
        headers=headers(issuer, subject, key or f"evaluation-{uuid4()}"),
        json={
            "workspace_id": workspace_id,
            "provider_path": "native_and_langchain",
            "include_langgraph": True,
            "langsmith_export_mode": langsmith_export_mode,
        },
    )


def test_offline_evaluation_runs_langchain_langgraph_and_local_langsmith_export(
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    response = run_evaluation(client, issuer)

    assert response.status_code == 201
    evaluation_run = response.json()["evaluation_run"]
    assert evaluation_run["status"] == "passed"
    assert evaluation_run["summary"]["total_cases"] == 6
    assert evaluation_run["summary"]["passed_cases"] == 6
    assert evaluation_run["summary"]["security_failed_cases"] == 0
    assert evaluation_run["summary"]["langchain_provider_exercised"] is True
    assert evaluation_run["summary"]["langgraph_exercised"] is True
    assert evaluation_run["summary"]["paid_provider_calls"] == 0
    cases = {case["case_key"]: case for case in evaluation_run["case_results"]}
    assert cases["langchain_fake_valid_plan"]["provider"] == "langchain_fake"
    assert cases["langchain_fake_valid_plan"]["artifacts"]["external_request_id"].startswith(
        "langchain-local:"
    )
    assert cases["langgraph_custom_parity"]["engine_kind"] == "custom+langgraph"
    assert cases["langgraph_step_limit_failure"]["status"] == "passed"
    assert cases["langgraph_step_limit_failure"]["security_critical"] is True
    assert evaluation_run["exports"][0]["status"] == "local_artifact"
    assert evaluation_run["exports"][0]["live_export"] is False
    metrics = {
        metric["metric_name"]: metric["metric_value"] for metric in evaluation_run["metrics"]
    }
    assert metrics["case_pass_rate"] == 1
    assert metrics["security_pass_rate"] == 1
    assert metrics["paid_provider_calls"] == 0


def test_evaluation_command_is_idempotent(client: TestClient, issuer: DevIssuer) -> None:
    key = f"evaluation-idempotent-{uuid4()}"

    first = run_evaluation(client, issuer, key=key)
    second = run_evaluation(client, issuer, key=key)
    conflict = client.post(
        "/v1/evaluations",
        headers=headers(issuer, key=key),
        json={
            "workspace_id": WORKSPACE_ID,
            "provider_path": "native_and_langchain",
            "include_langgraph": False,
            "langsmith_export_mode": "local",
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["evaluation_run"]["id"] == second.json()["evaluation_run"]["id"]
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_key_reused"


def test_langchain_provider_creates_validated_plan(client: TestClient, issuer: DevIssuer) -> None:
    workflow = next(
        workflow
        for workflow in client.get("/v1/workflows", headers=headers(issuer)).json()[
            "workflow_versions"
        ]
        if workflow["name"] == "Incident Response Demo"
    )
    run_response = client.post(
        "/v1/runs",
        headers=headers(issuer, key=f"langchain-provider-run-{uuid4()}"),
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Verify LangChain deterministic provider boundary.",
            "engine_kind": "custom",
        },
    )
    assert run_response.status_code == 201

    plan_response = client.post(
        f"/v1/runs/{run_response.json()['run']['id']}:plan",
        headers=headers(issuer, key=f"langchain-provider-plan-{uuid4()}"),
        json={
            "provider": "langchain_fake",
            "fake_scenario": "valid",
            "allow_correction": True,
            "objective_hint": "Create a bounded structured plan.",
        },
    )

    assert plan_response.status_code == 201
    body = plan_response.json()
    assert body["plan"]["status"] == "validated"
    assert body["model_call"]["provider"] == "langchain_fake"
    assert body["model_call"]["live_provider"] is False
    assert body["model_call"]["estimated_cost_minor"] == 0


@pytest.mark.security
def test_viewer_cannot_run_evaluations(client: TestClient, issuer: DevIssuer) -> None:
    response = run_evaluation(client, issuer, subject="bob")

    assert response.status_code == 403
    assert response.json()["code"] == "evaluation_run_forbidden"


@pytest.mark.security
def test_mallory_cannot_read_cross_tenant_evaluation(
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    created = run_evaluation(client, issuer)
    assert created.status_code == 201
    evaluation_id = created.json()["evaluation_run"]["id"]

    response = client.get(f"/v1/evaluations/{evaluation_id}", headers=headers(issuer, "mallory"))

    assert response.status_code == 404
    assert response.json()["code"] == "evaluation_run_not_found"


@pytest.mark.security
def test_live_langsmith_export_fails_closed_without_opt_in(
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    response = run_evaluation(client, issuer, langsmith_export_mode="enabled")

    assert response.status_code == 403
    assert response.json()["code"] == "langsmith_export_disabled"


@pytest.mark.security
def test_evaluation_suite_records_agent_attack_cases(
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    response = run_evaluation(client, issuer)
    assert response.status_code == 201
    cases = {
        case["case_key"]: case
        for case in response.json()["evaluation_run"]["case_results"]
        if case["security_critical"]
    }

    assert (
        EVALUATION_CASES_BY_KEY["langchain_hallucinated_tool_denied"].expected_outcome
        == "passed"
    )
    assert cases["langchain_hallucinated_tool_denied"]["status"] == "passed"
    assert cases["langchain_prompt_injection_contained"]["status"] == "passed"
    assert cases["langgraph_step_limit_failure"]["status"] == "passed"
