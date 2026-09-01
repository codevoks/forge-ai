"""Measured multi-agent patterns: router, specialist roles, and deterministic synthesis.

Forge does not adopt multi-agent execution by default (see decisions.md Q-006).
This module models the vocabulary Phase 12 needs to compare a single bounded
agentic workflow against isolated parallel specialists plus a deterministic
synthesizer, while keeping every authority decision (routing, aggregation,
role identity) in Forge application code rather than in model output.
"""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from forge_api.api.errors import ProblemError

MAX_SPECIALISTS = 4
MIN_SPECIALISTS = 2


class ExecutionStrategyKind(StrEnum):
    SINGLE_AGENTIC = "single_agentic"
    MULTI_AGENT_PARALLEL = "multi_agent_parallel"


STRATEGY_VERSIONS: dict[ExecutionStrategyKind, str] = {
    ExecutionStrategyKind.SINGLE_AGENTIC: "single-agentic-v1",
    ExecutionStrategyKind.MULTI_AGENT_PARALLEL: "multi-agent-parallel-v1",
}


def parse_execution_strategy_kind(value: str | None) -> ExecutionStrategyKind:
    if value is None:
        return ExecutionStrategyKind.SINGLE_AGENTIC
    try:
        return ExecutionStrategyKind(value)
    except ValueError as exc:
        raise ProblemError(
            422,
            "execution_strategy_invalid",
            "strategy_kind must be single_agentic or multi_agent_parallel.",
        ) from exc


def strategy_version_for(kind: ExecutionStrategyKind) -> str:
    return STRATEGY_VERSIONS[kind]


class SpecialistOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    SAFE_FAILURE = "safe_failure"


class AggregationPolicy(StrEnum):
    BEST_EFFORT = "best_effort"


@dataclass(frozen=True)
class SpecialistRoleDefinition:
    role: str
    display_name: str
    description: str
    keywords: tuple[str, ...]


# Code-owned specialist catalog, mirroring the code-registered tool catalog
# pattern in domain/tools.py: roles are never inferred from model output or
# authored ad hoc inside a workflow step; a step may only reference a role
# that Forge code already knows and has bounded.
SPECIALIST_ROLES: tuple[SpecialistRoleDefinition, ...] = (
    SpecialistRoleDefinition(
        role="deployment_specialist",
        display_name="Deployment specialist",
        description="Investigates recent deployment history for regressions.",
        keywords=("deploy", "deployment", "release", "rollout", "rollback"),
    ),
    SpecialistRoleDefinition(
        role="customer_impact_specialist",
        display_name="Customer impact specialist",
        description="Investigates customer-reported symptoms and severity.",
        keywords=("customer", "complaint", "report", "user", "impact"),
    ),
    SpecialistRoleDefinition(
        role="remediation_specialist",
        display_name="Remediation specialist",
        description=(
            "Proposes a simulated remediation ticket; requires exact-action approval "
            "like any other simulated_effect tool call."
        ),
        keywords=("remediate", "remediation", "ticket", "mitigate", "fix"),
    ),
    SpecialistRoleDefinition(
        role="release_notes_specialist",
        display_name="Release notes specialist",
        description=(
            "Searches Forge release notes for related recent changes via an enabled "
            "MCP tool (Phase 11). Used only by the optional MCP-integrated demo path; "
            "not part of the default zero-cost multi-agent workflow, which does not "
            "require any MCP server to be pre-enabled."
        ),
        keywords=("release note", "worker", "recovery", "outbox", "fencing"),
    ),
)

SPECIALIST_ROLES_BY_KEY: dict[str, SpecialistRoleDefinition] = {
    role.role: role for role in SPECIALIST_ROLES
}


def specialist_role_definition(role: str) -> SpecialistRoleDefinition:
    definition = SPECIALIST_ROLES_BY_KEY.get(role)
    if definition is None:
        raise ProblemError(422, "agent_role_unknown", f"Unknown specialist role: {role}.")
    return definition


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoutedSpecialist(StrictModel):
    role: str
    step_key: str
    selected: bool
    matched_keywords: list[str] = Field(default_factory=list)


class RoutingDecision(StrictModel):
    objective_hash: str
    specialists: list[RoutedSpecialist]
    fallback_selected_all: bool

    @property
    def selected_step_keys(self) -> set[str]:
        return {specialist.step_key for specialist in self.specialists if specialist.selected}

    @property
    def skipped_step_keys(self) -> set[str]:
        return {
            specialist.step_key for specialist in self.specialists if not specialist.selected
        }


class Router:
    """Deterministic, code-owned keyword router.

    Routing is never a model call: it must stay a reproducible, auditable
    Forge decision that untrusted objective text cannot steer beyond matching
    a fixed, code-owned keyword list. A model may later be plugged in behind
    this same interface (see decisions.md ADR-014), but no such model router
    is authoritative in this phase.
    """

    def route(
        self, *, objective: str, specialists: list[tuple[str, str]], objective_hash: str
    ) -> RoutingDecision:
        objective_lower = objective.lower()
        routed: list[RoutedSpecialist] = []
        for step_key, role in specialists:
            definition = specialist_role_definition(role)
            matched = [keyword for keyword in definition.keywords if keyword in objective_lower]
            routed.append(
                RoutedSpecialist(
                    role=role,
                    step_key=step_key,
                    selected=bool(matched),
                    matched_keywords=matched,
                )
            )
        fallback = False
        if routed and not any(specialist.selected for specialist in routed):
            # Safe default: no clear routing signal means run a comprehensive
            # investigation rather than silently skipping every specialist.
            routed = [specialist.model_copy(update={"selected": True}) for specialist in routed]
            fallback = True
        return RoutingDecision(
            objective_hash=objective_hash, specialists=routed, fallback_selected_all=fallback
        )


class SpecialistResult(StrictModel):
    step_key: str
    role: str
    outcome: SpecialistOutcome
    summary: str = Field(default="", max_length=1000)
    citations: list[str] = Field(default_factory=list, max_length=8)
    termination_reason: str | None = None
    iterations: int = Field(default=0, ge=0)
    tool_calls_used: int = Field(default=0, ge=0)
    model_calls_used: int = Field(default=0, ge=0)


class SynthesisResult(StrictModel):
    mode: str = "multi_agent_synthesis"
    overall_status: str
    aggregation_policy: AggregationPolicy = AggregationPolicy.BEST_EFFORT
    partial_failure: bool
    specialist_results: list[SpecialistResult]
    skipped_roles: list[str] = Field(default_factory=list)
    synthesized_summary: str = Field(max_length=2000)
    citations: list[str] = Field(default_factory=list, max_length=32)
    paid_provider_calls: int = 0


def parse_specialist_result(payload: object) -> SpecialistResult | None:
    """Best-effort parse of a sibling task's stored result as a SpecialistResult.

    Returns None for any task result that is not a well-formed specialist
    result (for example a non-specialist prerequisite) so the synthesizer can
    skip it deterministically rather than crash on an unexpected shape.
    """
    if not isinstance(payload, dict):
        return None
    try:
        return SpecialistResult.model_validate(payload)
    except Exception:  # noqa: BLE001 - deliberately tolerant, untrusted shape
        return None
