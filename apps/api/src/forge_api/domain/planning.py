import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from forge_api.api.errors import ProblemError
from forge_api.domain.workflow import DAGValidator, WorkflowEdgeDefinition, WorkflowStepDefinition

MAX_CONTEXT_INPUT_TOKENS = 1200
MAX_CONTEXT_ITEMS = 10
MAX_PLAN_NODES = 8
MAX_PLAN_EDGES = 16
MAX_CORRECTION_ATTEMPTS = 2


class ModelProviderKind(StrEnum):
    FAKE = "fake"
    LANGCHAIN_FAKE = "langchain_fake"
    OPENAI_COMPATIBLE = "openai_compatible"


class ModelCallStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUSED = "refused"
    MALFORMED = "malformed"
    POLICY_DENIED = "policy_denied"
    TIMEOUT = "timeout"


class PlanVersionStatus(StrEnum):
    VALIDATED = "validated"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class FakePlanningScenario(StrEnum):
    VALID = "valid"
    REPAIRABLE_MALFORMED = "repairable_malformed"
    HALLUCINATED_TOOL = "hallucinated_tool"
    CYCLIC_PLAN = "cyclic_plan"
    REFUSAL = "refusal"
    PROMPT_INJECTION = "prompt_injection"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PlanNodeProposal(StrictModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=2, max_length=120)
    kind: Literal["deterministic", "tool", "manual"]
    rationale: str = Field(min_length=2, max_length=1000)
    input: dict[str, Any] = Field(default_factory=dict)
    tool_name: str | None = Field(default=None, min_length=2, max_length=120)
    tool_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_tool_reference(self) -> "PlanNodeProposal":
        if self.kind == "tool":
            if self.tool_name is None or self.tool_version is None:
                raise ValueError("tool nodes require tool_name and tool_version")
            return self
        if self.tool_name is not None or self.tool_version is not None:
            raise ValueError("only tool nodes may include tool_name/tool_version")
        return self


class PlanEdgeProposal(StrictModel):
    from_key: str = Field(alias="from", min_length=1, max_length=64)
    to_key: str = Field(alias="to", min_length=1, max_length=64)


class StructuredPlanProposal(StrictModel):
    summary: str = Field(min_length=2, max_length=1000)
    nodes: list[PlanNodeProposal] = Field(min_length=1, max_length=MAX_PLAN_NODES)
    edges: list[PlanEdgeProposal] = Field(default_factory=list, max_length=MAX_PLAN_EDGES)


class PlanningContext(StrictModel):
    objective: str
    workflow_name: str
    allowed_tools: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    estimated_input_tokens: int
    max_input_tokens: int


class StructuredModelRequest(StrictModel):
    provider: ModelProviderKind
    model_name: str
    prompt_name: str
    prompt_version: int
    schema_name: str
    schema_version: int
    system_prompt: str
    context: PlanningContext
    correction_messages: list[str] = Field(default_factory=list, max_length=MAX_CORRECTION_ATTEMPTS)
    fake_scenario: FakePlanningScenario = FakePlanningScenario.VALID


class StructuredModelResult(StrictModel):
    provider: ModelProviderKind
    model_name: str
    status: ModelCallStatus
    raw_output: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    estimated_cost_minor: int = 0
    external_request_id: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    live_provider: bool = False


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def estimate_tokens(value: Any) -> int:
    text = canonical_json(value)
    return max(1, (len(text) + 3) // 4)


def parse_structured_plan(raw_output: str) -> StructuredPlanProposal:
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise ProblemError(
            422,
            "model_output_malformed",
            "Model output was not valid JSON.",
        ) from exc
    try:
        return StructuredPlanProposal.model_validate(payload)
    except ValidationError as exc:
        raise ProblemError(
            422,
            "model_output_schema_invalid",
            "Model output did not match the structured plan schema.",
        ) from exc


class PlanValidator:
    def validate(
        self,
        *,
        proposal: StructuredPlanProposal,
        allowed_tools: list[dict[str, Any]],
    ) -> list[str]:
        errors: list[str] = []
        tool_versions = {
            (str(tool["name"]), int(tool["version"]))
            for tool in allowed_tools
            if str(tool.get("status", "")) == "active"
        }
        keys = [node.key for node in proposal.nodes]
        if len(keys) != len(set(keys)):
            errors.append("Plan node keys must be unique.")
        if len(proposal.nodes) > MAX_PLAN_NODES:
            errors.append(f"Plan cannot exceed {MAX_PLAN_NODES} nodes.")
        if len(proposal.edges) > MAX_PLAN_EDGES:
            errors.append(f"Plan cannot exceed {MAX_PLAN_EDGES} edges.")
        for node in proposal.nodes:
            if node.kind == "tool" and (node.tool_name, node.tool_version) not in tool_versions:
                errors.append(f"Tool {node.tool_name} v{node.tool_version} is not allowed.")
        try:
            DAGValidator().validate(
                steps=[
                    WorkflowStepDefinition(
                        key=node.key,
                        name=node.title,
                        kind=node.kind,
                        input=node.input,
                    )
                    for node in proposal.nodes
                ],
                edges=[
                    WorkflowEdgeDefinition(from_key=edge.from_key, to_key=edge.to_key)
                    for edge in proposal.edges
                ],
            )
        except ProblemError as exc:
            errors.append(exc.message)
        return errors
