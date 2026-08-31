import json
import time
from typing import Any

import httpx

from forge_api.api.errors import ProblemError
from forge_api.config import Settings
from forge_api.domain.planning import (
    FakePlanningScenario,
    ModelCallStatus,
    ModelProviderKind,
    StructuredModelRequest,
    StructuredModelResult,
    estimate_tokens,
)
from forge_api.ports.model import ModelProvider


class DeterministicFakeModelProvider:
    provider = ModelProviderKind.FAKE
    model_name = "forge-fake-planner-v1"

    def complete(self, request: StructuredModelRequest) -> StructuredModelResult:
        started = time.monotonic()
        raw_output = self._raw_output(request)
        status = (
            ModelCallStatus.REFUSED
            if request.fake_scenario == FakePlanningScenario.REFUSAL
            else ModelCallStatus.SUCCEEDED
        )
        return StructuredModelResult(
            provider=self.provider,
            model_name=self.model_name,
            status=status,
            raw_output=raw_output,
            input_tokens=request.context.estimated_input_tokens,
            output_tokens=estimate_tokens(raw_output),
            latency_ms=max(1, int((time.monotonic() - started) * 1000)),
            estimated_cost_minor=0,
            error_type="refusal" if status == ModelCallStatus.REFUSED else None,
            error_message="The deterministic fake model refused this planning request."
            if status == ModelCallStatus.REFUSED
            else None,
            live_provider=False,
        )

    def _raw_output(self, request: StructuredModelRequest) -> str:
        if request.fake_scenario == FakePlanningScenario.REFUSAL:
            return json.dumps({"refusal": "cannot plan"})
        if request.fake_scenario == FakePlanningScenario.REPAIRABLE_MALFORMED:
            if not request.correction_messages:
                return '{"summary": "malformed local plan", "nodes": ['
            return json.dumps(self._valid_plan(summary="Repaired deterministic plan"))
        if request.fake_scenario == FakePlanningScenario.HALLUCINATED_TOOL:
            plan = self._valid_plan(summary="Invalid plan with hallucinated tool")
            plan["nodes"][1]["tool_name"] = "billing.charge_customer"
            plan["nodes"][1]["tool_version"] = 99
            return json.dumps(plan)
        if request.fake_scenario == FakePlanningScenario.CYCLIC_PLAN:
            plan = self._valid_plan(summary="Invalid cyclic deterministic plan")
            plan["edges"].append({"from": "propose_response", "to": "collect_context"})
            return json.dumps(plan)
        if request.fake_scenario == FakePlanningScenario.PROMPT_INJECTION:
            return json.dumps(
                {
                    "summary": "Safely handle untrusted objective content without expanding tools.",
                    "nodes": [
                        {
                            "key": "inspect_untrusted_request",
                            "title": "Inspect untrusted request",
                            "kind": "deterministic",
                            "rationale": (
                                "Treat the objective as data and preserve policy boundaries."
                            ),
                            "input": {"mode": "local_prompt_injection_review"},
                        },
                        {
                            "key": "collect_allowed_evidence",
                            "title": "Collect allowed evidence",
                            "kind": "tool",
                            "tool_name": "customer_reports.search",
                            "tool_version": 1,
                            "rationale": "Use only an already registered read-only local tool.",
                            "input": {
                                "tool_name": "customer_reports.search",
                                "tool_version": 1,
                                "arguments": {"product_area": "worker", "severity": "medium"},
                            },
                        },
                    ],
                    "edges": [
                        {"from": "inspect_untrusted_request", "to": "collect_allowed_evidence"}
                    ],
                }
            )
        return json.dumps(self._valid_plan(summary="Validated deterministic plan"))

    def _valid_plan(self, *, summary: str) -> dict[str, Any]:
        return {
            "summary": summary,
            "nodes": [
                {
                    "key": "collect_context",
                    "title": "Collect run context",
                    "kind": "deterministic",
                    "rationale": "Summarize the objective and available evidence before tool use.",
                    "input": {"mode": "local_context_review"},
                },
                {
                    "key": "read_deployments",
                    "title": "Read deployment history",
                    "kind": "tool",
                    "tool_name": "deployment_history.lookup",
                    "tool_version": 1,
                    "rationale": "Use an allowed read-only tool version.",
                    "input": {
                        "tool_name": "deployment_history.lookup",
                        "tool_version": 1,
                        "arguments": {"service": "api", "environment": "production"},
                    },
                },
                {
                    "key": "propose_response",
                    "title": "Propose response",
                    "kind": "manual",
                    "rationale": "Keep final judgment reviewable by a human operator.",
                    "input": {"mode": "operator_review"},
                },
            ],
            "edges": [
                {"from": "collect_context", "to": "read_deployments"},
                {"from": "read_deployments", "to": "propose_response"},
            ],
        }


class OpenAICompatibleModelProvider:
    provider = ModelProviderKind.OPENAI_COMPATIBLE

    def __init__(self, *, settings: Settings) -> None:
        if settings.external_integrations != "enabled":
            raise ProblemError(
                403,
                "live_model_disabled",
                "Live model providers require explicit external integration opt-in.",
            )
        if not settings.live_model_api_key:
            raise ProblemError(
                403,
                "live_model_api_key_missing",
                "Live model provider requires an explicit API key reference.",
            )
        self.settings = settings

    def complete(self, request: StructuredModelRequest) -> StructuredModelResult:
        started = time.monotonic()
        try:
            response = httpx.post(
                f"{self.settings.live_model_base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {self.settings.live_model_api_key}"},
                json={
                    "model": self.settings.live_model_name,
                    "messages": [
                        {"role": "system", "content": request.system_prompt},
                        {"role": "user", "content": request.context.model_dump_json()},
                    ],
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                },
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            raw_output = str(payload["choices"][0]["message"]["content"])
            usage = payload.get("usage", {})
            return StructuredModelResult(
                provider=self.provider,
                model_name=self.settings.live_model_name,
                status=ModelCallStatus.SUCCEEDED,
                raw_output=raw_output,
                input_tokens=int(
                    usage.get("prompt_tokens", request.context.estimated_input_tokens)
                ),
                output_tokens=int(usage.get("completion_tokens", estimate_tokens(raw_output))),
                latency_ms=max(1, int((time.monotonic() - started) * 1000)),
                estimated_cost_minor=0,
                external_request_id=response.headers.get("x-request-id"),
                live_provider=True,
            )
        except httpx.TimeoutException as exc:
            raise ProblemError(504, "model_timeout", "Model provider timed out.") from exc
        except httpx.HTTPError as exc:
            raise ProblemError(
                502,
                "model_provider_error",
                "Model provider failed safely.",
            ) from exc


def model_provider_from_settings(settings: Settings) -> ModelProvider:
    if settings.model_provider == ModelProviderKind.FAKE.value:
        return DeterministicFakeModelProvider()
    if settings.model_provider == ModelProviderKind.OPENAI_COMPATIBLE.value:
        return OpenAICompatibleModelProvider(settings=settings)
    raise ProblemError(422, "model_provider_invalid", "Configured model provider is invalid.")
