import json
from typing import Any

from forge_api.api.errors import ProblemError
from forge_api.application.tool_runtime import ToolRuntime
from forge_api.domain.agent import (
    AgentAllowedTool,
    AgentContextItem,
    AgentDecision,
    AgentDecisionStatus,
    AgentDecisionType,
    AgentDecisionValidator,
    AgentScenario,
    AgentState,
    AgentTerminationReason,
    FailurePayload,
    TerminationPolicy,
    parse_agent_decision,
    parse_agent_task_input,
)
from forge_api.infrastructure.agent_repositories import (
    AgentPromptRepository,
    AgentRepository,
)
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.workflow_repositories import EventRepository


class DeterministicAgentModel:
    def decide(self, *, state: AgentState, scenario: AgentScenario) -> str:
        if scenario == AgentScenario.STEP_LIMIT:
            return json.dumps(
                {
                    "decision": "tool_call",
                    "rationale": (
                        "Keep collecting deployment history until the application stops me."
                    ),
                    "tool_call": {
                        "tool_name": "deployment_history.lookup",
                        "tool_version": 1,
                        "arguments": {"service": "api", "environment": "production"},
                    },
                }
            )
        if scenario == AgentScenario.UNAUTHORIZED_TOOL:
            return json.dumps(
                {
                    "decision": "tool_call",
                    "rationale": "Attempt an ungranted billable tool to verify policy denial.",
                    "tool_call": {
                        "tool_name": "billing.charge_customer",
                        "tool_version": 99,
                        "arguments": {"amount": 5000, "currency": "INR"},
                    },
                }
            )
        if scenario == AgentScenario.PROMPT_INJECTION and not state.evidence:
            return json.dumps(
                {
                    "decision": "tool_call",
                    "rationale": "Use only granted local evidence despite hostile objective text.",
                    "tool_call": {
                        "tool_name": "customer_reports.search",
                        "tool_version": 1,
                        "arguments": {"product_area": "security", "severity": "high"},
                    },
                }
            )
        if scenario == AgentScenario.UNSUPPORTED_CLAIM and state.evidence:
            return json.dumps(
                {
                    "decision": "complete",
                    "rationale": "Return a conclusion with a forged evidence citation.",
                    "completion": {
                        "summary": "The incident is resolved, but this cites unsupported evidence.",
                        "citations": ["00000000-0000-0000-0000-000000000000"],
                    },
                }
            )
        if scenario == AgentScenario.REPLAN:
            return json.dumps(
                {
                    "decision": "request_replan",
                    "rationale": "Ask for a broader plan to verify constrained replan handling.",
                    "replan": {"reason": "Need broader authority."},
                }
            )
        if not state.evidence:
            return json.dumps(
                {
                    "decision": "tool_call",
                    "rationale": "Collect deterministic deployment evidence before concluding.",
                    "tool_call": {
                        "tool_name": "deployment_history.lookup",
                        "tool_version": 1,
                        "arguments": {"service": "api", "environment": "production"},
                    },
                }
            )
        return json.dumps(
            {
                "decision": "complete",
                "rationale": "Use persisted evidence to produce a cited result.",
                "completion": {
                    "summary": (
                        "Local deployment history was collected and no unsafe external provider "
                        "call was needed. The conclusion is grounded in the cited evidence."
                    ),
                    "citations": [state.evidence[0].evidence_item_id],
                },
            }
        )


class AgentRuntime:
    def __init__(self, *, database: Database) -> None:
        self.database = database
        self.model = DeterministicAgentModel()
        self.validator = AgentDecisionValidator()
        self.termination = TerminationPolicy()
        self.tool_runtime = ToolRuntime(database=database)

    def invoke_for_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        task_input = claim.get("input", {})
        if not isinstance(task_input, dict):
            raise ProblemError(422, "agent_task_invalid", "Agent task input must be an object.")
        agent_input = parse_agent_task_input(task_input)
        while True:
            state, prompt = self._build_state(claim=claim, agent_input=agent_input)
            terminated = self.termination.pre_decision(state)
            if terminated is not None:
                self._raise_termination(terminated, f"Agent stopped safely: {terminated.value}.")

            raw_output = self.model.decide(state=state, scenario=agent_input.scenario)
            try:
                decision = parse_agent_decision(raw_output)
                validation_errors = self.validator.validate(decision=decision, state=state)
            except ProblemError as exc:
                decision = AgentDecision(
                    decision=AgentDecisionType.FAIL,
                    rationale="The model returned invalid structure.",
                    failure=FailurePayload(reason=exc.message),
                )
                validation_errors = [exc.message]

            if validation_errors:
                self._record_iteration(
                    claim=claim,
                    prompt_version_id=str(prompt["id"]),
                    state=state,
                    raw_output=raw_output,
                    decision=decision,
                    status=AgentDecisionStatus.REJECTED,
                    validation_errors=validation_errors,
                    result={"errors": validation_errors},
                )
                next_state, _ = self._build_state(claim=claim, agent_input=agent_input)
                reason = self.termination.rejection_reason(next_state)
                if reason is not None:
                    self._raise_termination(
                        reason,
                        "Agent stopped after repeated invalid or no-progress decisions.",
                    )
                continue

            iteration = self._record_iteration(
                claim=claim,
                prompt_version_id=str(prompt["id"]),
                state=state,
                raw_output=raw_output,
                decision=decision,
                status=AgentDecisionStatus.VALIDATED,
                validation_errors=[],
                result={},
            )

            if decision.decision == AgentDecisionType.COMPLETE and decision.completion is not None:
                return {
                    "mode": "bounded_agent",
                    "status": "succeeded",
                    "termination_reason": AgentTerminationReason.COMPLETED.value,
                    "summary": decision.completion.summary,
                    "citations": decision.completion.citations,
                    "iterations": iteration["iteration_number"],
                    "paid_provider_calls": 0,
                }
            if decision.decision == AgentDecisionType.FAIL and decision.failure is not None:
                self._raise_termination(AgentTerminationReason.FAILED, decision.failure.reason)
            if decision.decision == AgentDecisionType.REQUEST_REPLAN:
                self._raise_termination(
                    AgentTerminationReason.REPLAN_NOT_AVAILABLE,
                    "Replan lineage is recorded, but execution-time replanning is deferred.",
                )
            if decision.decision == AgentDecisionType.TOOL_CALL and decision.tool_call is not None:
                tool_result = self.tool_runtime.invoke_for_claim(
                    claim
                    | {
                        "kind": "tool",
                        "input": {
                            "tool_name": decision.tool_call.tool_name,
                            "tool_version": decision.tool_call.tool_version,
                            "arguments": decision.tool_call.arguments,
                        },
                    }
                )
                self._mark_tool_observed(iteration_id=str(iteration["id"]), tool_result=tool_result)

    def _build_state(
        self,
        *,
        claim: dict[str, Any],
        agent_input: Any,
    ) -> tuple[AgentState, dict[str, Any]]:
        with self.database.transaction(worker_id=str(claim["worker_id"])) as conn:
            prompt_repo = AgentPromptRepository(conn)
            prompt_repo.sync_builtin_prompt()
            prompt = prompt_repo.get_active_prompt()
            repo = AgentRepository(conn)
            evidence = repo.recent_evidence(
                run_id=str(claim["run_id"]),
                limit=agent_input.budgets.max_context_items,
            )
            model_calls_used = repo.count_model_calls(task_id=str(claim["task_id"]))
            state = AgentState(
                objective=agent_input.objective,
                iteration_number=model_calls_used + 1,
                tool_calls_used=repo.count_tool_calls(task_id=str(claim["task_id"])),
                model_calls_used=model_calls_used,
                invalid_decisions=repo.count_invalid_decisions(task_id=str(claim["task_id"])),
                no_progress_decisions=repo.count_no_progress_decisions(
                    task_id=str(claim["task_id"])
                ),
                allowed_tools=[
                    AgentAllowedTool(
                        tool_name=tool.tool_name,
                        tool_version=tool.tool_version,
                    )
                    for tool in agent_input.allowed_tools
                ],
                evidence=[AgentContextItem.model_validate(item) for item in evidence],
                budgets=agent_input.budgets,
            )
            return state, prompt

    def _record_iteration(
        self,
        *,
        claim: dict[str, Any],
        prompt_version_id: str,
        state: AgentState,
        raw_output: str,
        decision: AgentDecision,
        status: AgentDecisionStatus,
        validation_errors: list[str],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        with self.database.transaction(worker_id=str(claim["worker_id"])) as conn:
            repo = AgentRepository(conn)
            model_call = repo.record_model_call(
                tenant_id=str(claim["tenant_id"]),
                workspace_id=str(claim["workspace_id"]),
                run_id=str(claim["run_id"]),
                prompt_version_id=prompt_version_id,
                state=state,
                raw_output=raw_output,
                status="succeeded" if status == AgentDecisionStatus.VALIDATED else "failed",
                error_type="agent_decision_rejected" if validation_errors else None,
                error_message="; ".join(validation_errors) if validation_errors else None,
            )
            iteration = repo.record_iteration(
                tenant_id=str(claim["tenant_id"]),
                workspace_id=str(claim["workspace_id"]),
                run_id=str(claim["run_id"]),
                task_id=str(claim["task_id"]),
                attempt_id=str(claim["attempt_id"]),
                model_call_id=str(model_call["id"]),
                state=state,
                decision_type=decision.decision,
                decision_status=status,
                decision_payload=decision.model_dump(mode="json"),
                validation_errors=validation_errors,
                result=result,
            )
            EventRepository(conn).append(
                tenant_id=str(claim["tenant_id"]),
                workspace_id=str(claim["workspace_id"]),
                run_id=str(claim["run_id"]),
                task_id=str(claim["task_id"]),
                aggregate_type="agent_iteration",
                aggregate_id=str(iteration["id"]),
                event_type=(
                    "agent.iteration.validated"
                    if status == AgentDecisionStatus.VALIDATED
                    else "agent.iteration.rejected"
                ),
                actor_id=str(claim["actor_id"]),
                payload={
                    "iteration_number": iteration["iteration_number"],
                    "decision_type": decision.decision.value,
                    "decision_status": status.value,
                    "validation_error_count": len(validation_errors),
                },
            )
            return iteration

    def _mark_tool_observed(self, *, iteration_id: str, tool_result: dict[str, Any]) -> None:
        with self.database.transaction(worker_id="forge-agent-runtime") as conn:
            conn.execute(
                """
                update agent_iterations
                set tool_invocation_id = %s,
                    evidence_item_id = %s,
                    result = %s
                where id = %s
                """,
                (
                    tool_result.get("invocation_id"),
                    tool_result.get("evidence", {}).get("id")
                    if isinstance(tool_result.get("evidence"), dict)
                    else None,
                    json.dumps({"tool_result": tool_result}),
                    iteration_id,
                ),
            )

    def _raise_termination(self, reason: AgentTerminationReason, message: str) -> None:
        raise ProblemError(409, reason.value, message)
