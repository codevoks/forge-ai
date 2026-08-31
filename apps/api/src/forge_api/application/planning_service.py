from typing import Any, cast

from forge_api.api.errors import ProblemError
from forge_api.config import Settings
from forge_api.domain.identity import ActorContext, Capability
from forge_api.domain.planning import (
    MAX_CONTEXT_INPUT_TOKENS,
    MAX_CONTEXT_ITEMS,
    MAX_CORRECTION_ATTEMPTS,
    FakePlanningScenario,
    ModelCallStatus,
    ModelProviderKind,
    PlanningContext,
    PlanValidator,
    PlanVersionStatus,
    StructuredModelRequest,
    StructuredModelResult,
    StructuredPlanProposal,
    estimate_tokens,
    parse_structured_plan,
    stable_hash,
)
from forge_api.domain.workflow import validate_payload_size
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.model_providers import (
    DeterministicFakeModelProvider,
    OpenAICompatibleModelProvider,
)
from forge_api.infrastructure.planning_repositories import (
    PlanningRepository,
    PromptRegistryRepository,
)
from forge_api.infrastructure.repositories import IdempotencyRepository, canonical_hash
from forge_api.infrastructure.tool_repositories import ToolRegistryRepository
from forge_api.infrastructure.workflow_repositories import EventRepository, RunRepository
from forge_api.policy.authorization import AuthorizationService
from forge_api.ports.model import ModelProvider


class ContextBuilder:
    def build(
        self,
        *,
        run: dict[str, Any],
        allowed_tools: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
    ) -> PlanningContext:
        tool_projection = [
            {
                "name": tool["name"],
                "version": tool["version"],
                "status": tool["status"],
                "risk": tool["risk"],
                "description": tool["description"],
                "input_schema": tool["input_schema"],
            }
            for tool in allowed_tools
        ]
        evidence_projection = [
            {
                "source_type": item["source_type"],
                "source_name": item["source_name"],
                "trust_label": item["trust_label"],
                "summary": item["summary"],
                "content_hash": item["content_hash"],
            }
            for item in evidence[:MAX_CONTEXT_ITEMS]
        ]
        context = PlanningContext(
            objective=str(run["objective"]),
            workflow_name=str(run["workflow_name"]),
            allowed_tools=tool_projection,
            evidence=evidence_projection,
            estimated_input_tokens=1,
            max_input_tokens=MAX_CONTEXT_INPUT_TOKENS,
        )
        estimated_input_tokens = estimate_tokens(context.model_dump(mode="json"))
        if estimated_input_tokens > MAX_CONTEXT_INPUT_TOKENS:
            raise ProblemError(
                422,
                "planning_context_too_large",
                "The planning context exceeds the local deterministic budget.",
            )
        return context.model_copy(update={"estimated_input_tokens": estimated_input_tokens})


class PlannerService:
    def __init__(self, database: Database, settings: Settings | None = None) -> None:
        self.database = database
        self.settings = settings or Settings()
        self.context_builder = ContextBuilder()
        self.validator = PlanValidator()

    def plan_run(
        self,
        actor: ActorContext,
        run_id: str,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        validate_payload_size(
            str(payload.get("objective_hint", "Plan this run.")),
            field="objective",
        )
        provider_kind = ModelProviderKind(
            str(payload.get("provider", self.settings.model_provider))
        )
        fake_scenario = FakePlanningScenario(
            str(payload.get("fake_scenario", FakePlanningScenario.VALID.value))
        )
        allow_correction = bool(payload.get("allow_correction", True))
        request_hash = canonical_hash(payload)
        scope = f"user:{actor.user_id}:run-plan:{run_id}"

        with self.database.transaction(actor_id=actor.user_id) as conn:
            run = RunRepository(conn).get_run_for_actor(actor_id=actor.user_id, run_id=run_id)
            decision = AuthorizationService().decide_workspace(
                actor,
                str(run["workspace_id"]),
                Capability.RUN_CREATE,
            )
            if not decision.allowed:
                raise ProblemError(403, "run_plan_forbidden", "Run planning is not allowed.")
            tenant_id = str(run["tenant_id"])

        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            idempotency = IdempotencyRepository(conn)
            existing = idempotency.existing(scope, idempotency_key)
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise ProblemError(
                        409,
                        "idempotency_key_reused",
                        "The Idempotency-Key was already used with a different request.",
                    )
                response_payload = existing["response_payload"]
                if not isinstance(response_payload, dict):
                    raise ProblemError(
                        500,
                        "idempotency_record_invalid",
                        "Stored response is invalid.",
                    )
                return response_payload

        provider = self._provider_for(provider_kind)

        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            prompt_registry = PromptRegistryRepository(conn)
            prompt_registry.sync_builtin_prompts()
            prompt = prompt_registry.get_active_planner_prompt()
            allowed_tools = ToolRegistryRepository(conn).list_for_actor(actor_id=actor.user_id)
            run = RunRepository(conn).get_run_for_actor(actor_id=actor.user_id, run_id=run_id)
            evidence = self._recent_evidence(conn, run_id=run_id)
            context = self.context_builder.build(
                run=run,
                allowed_tools=allowed_tools,
                evidence=evidence,
            )

        response = self._attempt_plan(
            actor=actor,
            run=run,
            prompt=prompt,
            context=context,
            provider=provider,
            provider_kind=provider_kind,
            fake_scenario=fake_scenario,
            allow_correction=allow_correction,
        )

        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            IdempotencyRepository(conn).save(
                scope=scope,
                key=idempotency_key,
                request_hash=request_hash,
                response_payload=response,
                status_code=201,
            )
        return response

    def list_plans(self, actor: ActorContext, run_id: str) -> list[dict[str, Any]]:
        tenant_id = self._tenant_for_run(actor, run_id)
        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            return PlanningRepository(conn).list_plans_for_actor(
                actor_id=actor.user_id,
                run_id=run_id,
            )

    def list_model_calls(self, actor: ActorContext, run_id: str) -> list[dict[str, Any]]:
        tenant_id = self._tenant_for_run(actor, run_id)
        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            return PlanningRepository(conn).list_model_calls_for_actor(
                actor_id=actor.user_id,
                run_id=run_id,
            )

    def _attempt_plan(
        self,
        *,
        actor: ActorContext,
        run: dict[str, Any],
        prompt: dict[str, Any],
        context: PlanningContext,
        provider: ModelProvider,
        provider_kind: ModelProviderKind,
        fake_scenario: FakePlanningScenario,
        allow_correction: bool,
    ) -> dict[str, Any]:
        correction_messages: list[str] = []
        max_attempts = 1 + (MAX_CORRECTION_ATTEMPTS if allow_correction else 0)
        last_response: dict[str, Any] | None = None
        for attempt_index in range(max_attempts):
            request = StructuredModelRequest(
                provider=provider_kind,
                model_name=getattr(provider, "model_name", self.settings.live_model_name),
                prompt_name=str(prompt["name"]),
                prompt_version=int(prompt["version"]),
                schema_name=str(prompt["schema_name"]),
                schema_version=int(prompt["schema_version"]),
                system_prompt=str(prompt["template"]),
                context=context,
                correction_messages=correction_messages,
                fake_scenario=fake_scenario,
            )
            result = provider.complete(request)
            plan, validation_errors, status, summary = self._parse_and_validate(
                result=result,
                allowed_tools=context.allowed_tools,
            )
            response = self._persist_attempt(
                actor=actor,
                run=run,
                prompt=prompt,
                request=request,
                result=result,
                plan=plan,
                validation_errors=validation_errors,
                status=status,
                summary=summary,
                corrected=attempt_index > 0,
            )
            if status == PlanVersionStatus.VALIDATED:
                return response
            last_response = response
            if not allow_correction or attempt_index >= max_attempts - 1:
                return response
            correction_messages.append(
                "Previous output failed validation. Return strict JSON using only allowed tools. "
                f"Errors: {'; '.join(validation_errors)}"
            )
        if last_response is None:
            raise ProblemError(500, "planner_unavailable", "Planner did not return a response.")
        return last_response

    def _parse_and_validate(
        self,
        *,
        result: StructuredModelResult,
        allowed_tools: list[dict[str, Any]],
    ) -> tuple[StructuredPlanProposal | None, list[str], PlanVersionStatus, str]:
        if result.status == ModelCallStatus.REFUSED:
            return (
                None,
                ["Model refused to produce a structured plan."],
                PlanVersionStatus.REJECTED,
                "Model refused to produce a structured plan.",
            )
        try:
            plan = parse_structured_plan(result.raw_output)
        except ProblemError as exc:
            return None, [exc.message], PlanVersionStatus.REJECTED, "Structured output rejected."
        validation_errors = self.validator.validate(proposal=plan, allowed_tools=allowed_tools)
        if validation_errors:
            return plan, validation_errors, PlanVersionStatus.REJECTED, plan.summary
        return plan, [], PlanVersionStatus.VALIDATED, plan.summary

    def _persist_attempt(
        self,
        *,
        actor: ActorContext,
        run: dict[str, Any],
        prompt: dict[str, Any],
        request: StructuredModelRequest,
        result: StructuredModelResult,
        plan: StructuredPlanProposal | None,
        validation_errors: list[str],
        status: PlanVersionStatus,
        summary: str,
        corrected: bool,
    ) -> dict[str, Any]:
        tenant_id = str(run["tenant_id"])
        workspace_id = str(run["workspace_id"])
        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            planning_repo = PlanningRepository(conn)
            model_status = result.status
            if status == PlanVersionStatus.REJECTED and result.status == ModelCallStatus.SUCCEEDED:
                model_status = ModelCallStatus.MALFORMED if plan is None else ModelCallStatus.FAILED
            model_call = planning_repo.record_model_call(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                run_id=str(run["id"]),
                prompt_version_id=str(prompt["id"]),
                request=request,
                result=result,
                status=model_status,
                response_summary={
                    "raw_output_hash": stable_hash(result.raw_output),
                    "structured": plan is not None,
                    "corrected": corrected,
                    "validation_error_count": len(validation_errors),
                },
                error_type="plan_validation_failed" if validation_errors else result.error_type,
                error_message="; ".join(validation_errors)
                if validation_errors
                else result.error_message,
            )
            plan_version = planning_repo.create_plan_version(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                run_id=str(run["id"]),
                actor_id=actor.user_id,
                prompt_version_id=str(prompt["id"]),
                model_call_id=str(model_call["id"]),
                objective=str(run["objective"]),
                summary=summary,
                status=status,
                validation_errors=validation_errors,
                proposal=plan if status == PlanVersionStatus.VALIDATED else None,
            )
            EventRepository(conn).append(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                run_id=str(run["id"]),
                task_id=None,
                aggregate_type="plan",
                aggregate_id=str(plan_version["id"]),
                event_type="plan.validated"
                if status == PlanVersionStatus.VALIDATED
                else "plan.rejected",
                actor_id=actor.user_id,
                payload={
                    "plan_version_id": plan_version["id"],
                    "model_call_id": model_call["id"],
                    "provider": result.provider.value,
                    "live_provider": result.live_provider,
                    "corrected": corrected,
                    "validation_error_count": len(validation_errors),
                },
            )
        return {
            "plan": plan_version,
            "model_call": model_call,
            "corrected": corrected,
            "zero_cost": {
                "provider": result.provider.value,
                "live_provider": result.live_provider,
                "estimated_cost_minor": result.estimated_cost_minor,
            },
        }

    def _provider_for(self, provider_kind: ModelProviderKind) -> ModelProvider:
        if provider_kind == ModelProviderKind.FAKE:
            return DeterministicFakeModelProvider()
        if provider_kind == ModelProviderKind.OPENAI_COMPATIBLE:
            return OpenAICompatibleModelProvider(settings=self.settings)
        raise ProblemError(422, "model_provider_invalid", "Requested model provider is invalid.")

    def _tenant_for_run(self, actor: ActorContext, run_id: str) -> str:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            run = RunRepository(conn).get_run_for_actor(actor_id=actor.user_id, run_id=run_id)
            return str(run["tenant_id"])

    def _recent_evidence(self, conn: Any, *, run_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            select source_type, source_name, trust_label, summary, content_hash
            from evidence_items
            where run_id = %s
            order by created_at desc
            limit %s
            """,
            (run_id, MAX_CONTEXT_ITEMS),
        ).fetchall()
        return cast(list[dict[str, Any]], rows)
