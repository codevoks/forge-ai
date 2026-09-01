import hashlib
import json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from forge_api.api.errors import ProblemError
from forge_api.domain.planning import estimate_tokens

MAX_AGENT_ITERATIONS = 6
MAX_AGENT_TOOL_CALLS = 4
MAX_AGENT_MODEL_CALLS = 6
MAX_AGENT_CONTEXT_ITEMS = 6
MAX_AGENT_INVALID_DECISIONS = 2
MAX_AGENT_NO_PROGRESS_DECISIONS = 2
MAX_AGENT_OUTPUT_TOKENS = 800


class AgentScenario(StrEnum):
    SUCCESS = "success"
    STEP_LIMIT = "step_limit"
    UNAUTHORIZED_TOOL = "unauthorized_tool"
    PROMPT_INJECTION = "prompt_injection"
    UNSUPPORTED_CLAIM = "unsupported_claim"
    REPLAN = "replan"
    APPROVAL_INTERRUPT = "approval_interrupt"


class AgentDecisionType(StrEnum):
    TOOL_CALL = "tool_call"
    COMPLETE = "complete"
    FAIL = "fail"
    REQUEST_REPLAN = "request_replan"


class AgentDecisionStatus(StrEnum):
    VALIDATED = "validated"
    REJECTED = "rejected"


class AgentTerminationReason(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    STEP_LIMIT_REACHED = "step_limit_reached"
    TOOL_BUDGET_EXHAUSTED = "tool_budget_exhausted"
    MODEL_BUDGET_EXHAUSTED = "model_budget_exhausted"
    INVALID_DECISION_LIMIT_REACHED = "invalid_decision_limit_reached"
    NO_PROGRESS_LIMIT_REACHED = "no_progress_limit_reached"
    REPLAN_NOT_AVAILABLE = "replan_not_available"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AgentBudget(StrictModel):
    max_iterations: int = Field(default=MAX_AGENT_ITERATIONS, ge=1, le=MAX_AGENT_ITERATIONS)
    max_tool_calls: int = Field(default=MAX_AGENT_TOOL_CALLS, ge=0, le=MAX_AGENT_TOOL_CALLS)
    max_model_calls: int = Field(default=MAX_AGENT_MODEL_CALLS, ge=1, le=MAX_AGENT_MODEL_CALLS)
    max_context_items: int = Field(
        default=MAX_AGENT_CONTEXT_ITEMS,
        ge=1,
        le=MAX_AGENT_CONTEXT_ITEMS,
    )
    max_invalid_decisions: int = Field(
        default=MAX_AGENT_INVALID_DECISIONS,
        ge=0,
        le=MAX_AGENT_INVALID_DECISIONS,
    )
    max_no_progress_decisions: int = Field(
        default=MAX_AGENT_NO_PROGRESS_DECISIONS,
        ge=0,
        le=MAX_AGENT_NO_PROGRESS_DECISIONS,
    )
    max_output_tokens: int = Field(
        default=MAX_AGENT_OUTPUT_TOKENS,
        ge=64,
        le=MAX_AGENT_OUTPUT_TOKENS,
    )


class AgentAllowedTool(StrictModel):
    tool_name: str = Field(min_length=2, max_length=120)
    tool_version: int = Field(ge=1)


class AgentTaskInput(StrictModel):
    scenario: AgentScenario = AgentScenario.SUCCESS
    objective: str = Field(min_length=2, max_length=4096)
    allowed_tools: list[AgentAllowedTool] = Field(min_length=1, max_length=4)
    budgets: AgentBudget = Field(default_factory=AgentBudget)
    agent_role: str | None = Field(default=None, min_length=2, max_length=60)


class AgentContextItem(StrictModel):
    evidence_item_id: str
    source_name: str
    trust_label: str
    content_hash: str
    summary: dict[str, Any]


class AgentState(StrictModel):
    objective: str
    iteration_number: int
    tool_calls_used: int
    model_calls_used: int
    invalid_decisions: int
    no_progress_decisions: int
    allowed_tools: list[AgentAllowedTool]
    evidence: list[AgentContextItem]
    budgets: AgentBudget


class ToolCallPayload(StrictModel):
    tool_name: str = Field(min_length=2, max_length=120)
    tool_version: int = Field(ge=1)
    arguments: dict[str, Any]


class CompletionPayload(StrictModel):
    summary: str = Field(min_length=2, max_length=1000)
    citations: list[str] = Field(min_length=1, max_length=8)


class FailurePayload(StrictModel):
    reason: str = Field(min_length=2, max_length=500)


class ReplanPayload(StrictModel):
    reason: str = Field(min_length=2, max_length=500)


class AgentDecision(StrictModel):
    decision: AgentDecisionType
    rationale: str = Field(min_length=2, max_length=1000)
    tool_call: ToolCallPayload | None = None
    completion: CompletionPayload | None = None
    failure: FailurePayload | None = None
    replan: ReplanPayload | None = None

    @model_validator(mode="after")
    def validate_matching_payload(self) -> "AgentDecision":
        payloads = {
            AgentDecisionType.TOOL_CALL: self.tool_call,
            AgentDecisionType.COMPLETE: self.completion,
            AgentDecisionType.FAIL: self.failure,
            AgentDecisionType.REQUEST_REPLAN: self.replan,
        }
        if payloads[self.decision] is None:
            raise ValueError("decision payload is required")
        for kind, payload in payloads.items():
            if kind != self.decision and payload is not None:
                raise ValueError("only the matching decision payload is allowed")
        return self


def parse_agent_task_input(payload: dict[str, Any]) -> AgentTaskInput:
    try:
        return AgentTaskInput.model_validate(payload)
    except ValidationError as exc:
        raise ProblemError(422, "agent_task_invalid", "Agent task input is invalid.") from exc


def parse_agent_decision(raw_output: str) -> AgentDecision:
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise ProblemError(
            422,
            "agent_output_malformed",
            "Agent output was not valid JSON.",
        ) from exc
    try:
        return AgentDecision.model_validate(payload)
    except ValidationError as exc:
        raise ProblemError(
            422,
            "agent_output_schema_invalid",
            "Agent output did not match the decision schema.",
        ) from exc


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def estimated_decision_tokens(raw_output: str) -> int:
    return estimate_tokens(raw_output)


class AgentDecisionValidator:
    def validate(self, *, decision: AgentDecision, state: AgentState) -> list[str]:
        errors: list[str] = []
        if decision.decision == AgentDecisionType.TOOL_CALL:
            tool_call = decision.tool_call
            if tool_call is None:
                errors.append("Tool call decision is missing payload.")
            else:
                allowed = {
                    (tool.tool_name, tool.tool_version) for tool in state.allowed_tools
                }
                if (tool_call.tool_name, tool_call.tool_version) not in allowed:
                    errors.append(
                        f"Tool {tool_call.tool_name} v{tool_call.tool_version} is not allowed."
                    )
                if state.tool_calls_used >= state.budgets.max_tool_calls:
                    errors.append("Agent tool-call budget is exhausted.")
        if decision.decision == AgentDecisionType.COMPLETE:
            completion = decision.completion
            if completion is None:
                errors.append("Completion decision is missing payload.")
            else:
                evidence_ids = {item.evidence_item_id for item in state.evidence}
                missing = [
                    citation for citation in completion.citations if citation not in evidence_ids
                ]
                if missing:
                    errors.append("Completion includes unsupported evidence citations.")
                if estimated_decision_tokens(completion.summary) > state.budgets.max_output_tokens:
                    errors.append("Completion summary exceeds the output budget.")
        if decision.decision == AgentDecisionType.REQUEST_REPLAN:
            errors.append("Replan requests are recorded, but replanning is deferred in Phase 7.")
        return errors


class TerminationPolicy:
    def pre_decision(self, state: AgentState) -> AgentTerminationReason | None:
        if state.iteration_number > state.budgets.max_iterations:
            return AgentTerminationReason.STEP_LIMIT_REACHED
        if state.model_calls_used >= state.budgets.max_model_calls:
            return AgentTerminationReason.MODEL_BUDGET_EXHAUSTED
        if state.invalid_decisions > state.budgets.max_invalid_decisions:
            return AgentTerminationReason.INVALID_DECISION_LIMIT_REACHED
        if state.no_progress_decisions > state.budgets.max_no_progress_decisions:
            return AgentTerminationReason.NO_PROGRESS_LIMIT_REACHED
        return None

    def rejection_reason(self, state: AgentState) -> AgentTerminationReason | None:
        if state.invalid_decisions >= state.budgets.max_invalid_decisions:
            return AgentTerminationReason.INVALID_DECISION_LIMIT_REACHED
        if state.no_progress_decisions >= state.budgets.max_no_progress_decisions:
            return AgentTerminationReason.NO_PROGRESS_LIMIT_REACHED
        return None
