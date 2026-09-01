from pprint import pprint
from uuid import uuid4

from fastapi.testclient import TestClient

from forge_api.config import Settings
from forge_api.infrastructure.dev_issuer import DevIssuer
from forge_api.main import create_app
from forge_api.scripts.seed import WORKSPACE_ID
from forge_api.scripts.seed import main as seed_main


def _headers(issuer: DevIssuer, *, key: str | None = None) -> dict[str, str]:
    token = issuer.token_for_subject(
        subject="oidc|alice",
        email="alice@forge.local",
        name="Alice Admin",
    )
    headers = {"Authorization": f"Bearer {token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def main() -> None:
    settings = Settings()
    settings.assert_zero_cost_safe()
    seed_main()
    client = TestClient(create_app())
    issuer = DevIssuer(settings.oidc_issuer, settings.oidc_audience, settings.oidc_jwks_path)

    response = client.post(
        "/v1/evaluations",
        headers=_headers(issuer, key=f"demo-evaluation-{uuid4()}"),
        json={
            "workspace_id": WORKSPACE_ID,
            "provider_path": "native_and_langchain",
            "include_langgraph": True,
            "langsmith_export_mode": "local",
        },
    )
    response.raise_for_status()
    evaluation_run = response.json()["evaluation_run"]

    print("Forge offline evaluation and framework-boundary demo")
    pprint(
        {
            "evaluation_status": evaluation_run["status"],
            "summary": evaluation_run["summary"],
            "cases": [
                {
                    "case_key": case["case_key"],
                    "status": case["status"],
                    "category": case["category"],
                    "security_critical": case["security_critical"],
                    "provider": case["provider"],
                    "engine_kind": case["engine_kind"],
                }
                for case in evaluation_run["case_results"]
            ],
            "metrics": {
                metric["metric_name"]: metric["metric_value"]
                for metric in evaluation_run["metrics"]
            },
            "langsmith_export": evaluation_run["exports"][0],
        }
    )

    blocked = client.post(
        "/v1/evaluations",
        headers=_headers(issuer, key=f"demo-langsmith-blocked-{uuid4()}"),
        json={
            "workspace_id": WORKSPACE_ID,
            "provider_path": "native_and_langchain",
            "include_langgraph": True,
            "langsmith_export_mode": "enabled",
        },
    )
    print(
        {
            "live_langsmith_without_opt_in_status": blocked.status_code,
            "live_langsmith_without_opt_in_code": blocked.json()["code"],
            "paid_provider_calls": 0,
            "external_integrations": settings.external_integrations,
        }
    )


if __name__ == "__main__":
    main()
