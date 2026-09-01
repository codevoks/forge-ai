from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvaluationStatus(StrEnum):
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"


class EvaluationCaseCategory(StrEnum):
    PLANNING = "planning"
    AGENT = "agent"
    SECURITY = "security"
    FAILURE = "failure"


class EvaluationCaseStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class MetricProvenance(StrEnum):
    DETERMINISTIC = "deterministic"
    SYNTHETIC = "synthetic"
    MEASURED_LOCAL = "measured_local"


class LangSmithExportStatus(StrEnum):
    DISABLED = "disabled"
    LOCAL_ARTIFACT = "local_artifact"
    BLOCKED = "blocked"
    EXPORTED = "exported"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EvaluationCaseDefinition(StrictModel):
    key: str = Field(min_length=2, max_length=120)
    category: EvaluationCaseCategory
    description: str = Field(min_length=2, max_length=500)
    security_critical: bool = False
    expected_outcome: dict[str, Any] = Field(default_factory=dict)


class EvaluationCaseOutcome(StrictModel):
    case_key: str = Field(min_length=2, max_length=120)
    category: EvaluationCaseCategory
    status: EvaluationCaseStatus
    security_critical: bool
    provider: str = Field(min_length=2, max_length=120)
    engine_kind: str | None = None
    metrics: dict[str, float | int | str | bool] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)
    failure_message: str | None = Field(default=None, max_length=500)


class MetricRecord(StrictModel):
    name: str = Field(min_length=2, max_length=120)
    value: float
    unit: str = Field(min_length=1, max_length=40)
    provenance: MetricProvenance
    case_key: str | None = Field(default=None, min_length=2, max_length=120)


PHASE9_SUITE_NAME = "forge.offline_regression"
PHASE9_SUITE_VERSION = 1
PHASE9_SUITE_DESCRIPTION = (
    "Offline deterministic evaluation suite covering planner, LangChain, LangGraph, "
    "security, and failure-injection boundaries."
)


PHASE9_CASES: tuple[EvaluationCaseDefinition, ...] = (
    EvaluationCaseDefinition(
        key="native_fake_valid_plan",
        category=EvaluationCaseCategory.PLANNING,
        description="Native fake planner creates a validated structured plan.",
        expected_outcome={"plan_status": "validated", "provider": "fake"},
    ),
    EvaluationCaseDefinition(
        key="langchain_fake_valid_plan",
        category=EvaluationCaseCategory.PLANNING,
        description="LangChain-backed deterministic adapter creates an equivalent plan.",
        expected_outcome={"plan_status": "validated", "provider": "langchain_fake"},
    ),
    EvaluationCaseDefinition(
        key="langchain_hallucinated_tool_denied",
        category=EvaluationCaseCategory.SECURITY,
        description="LangChain adapter cannot expand allowed tool authority.",
        security_critical=True,
        expected_outcome={"plan_status": "rejected", "error_contains": "not allowed"},
    ),
    EvaluationCaseDefinition(
        key="langchain_prompt_injection_contained",
        category=EvaluationCaseCategory.SECURITY,
        description="Prompt-injected objective remains inside the Forge tool projection.",
        security_critical=True,
        expected_outcome={"allowed_tool": "customer_reports.search", "forbidden_tool": "billing"},
    ),
    EvaluationCaseDefinition(
        key="langgraph_custom_parity",
        category=EvaluationCaseCategory.AGENT,
        description="Custom and LangGraph engines complete the same bounded agent case.",
        expected_outcome={"same_terminal_status": True, "same_decision_types": True},
    ),
    EvaluationCaseDefinition(
        key="langgraph_step_limit_failure",
        category=EvaluationCaseCategory.FAILURE,
        description="LangGraph bounded-agent step-limit scenario fails closed.",
        security_critical=True,
        expected_outcome={"run_status": "failed", "outcome": "policy_denied"},
    ),
)
