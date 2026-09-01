import pytest

from forge_api.api.errors import ProblemError
from forge_api.domain.multi_agent import (
    MAX_SPECIALISTS,
    Router,
    SpecialistOutcome,
    SynthesisResult,
    parse_execution_strategy_kind,
    parse_specialist_result,
    specialist_role_definition,
    strategy_version_for,
)


def test_parse_execution_strategy_kind_defaults_to_single_agentic() -> None:
    kind = parse_execution_strategy_kind(None)
    assert kind.value == "single_agentic"
    assert strategy_version_for(kind) == "single-agentic-v1"


def test_parse_execution_strategy_kind_accepts_multi_agent() -> None:
    kind = parse_execution_strategy_kind("multi_agent_parallel")
    assert strategy_version_for(kind) == "multi-agent-parallel-v1"


def test_parse_execution_strategy_kind_rejects_unknown() -> None:
    with pytest.raises(ProblemError) as exc_info:
        parse_execution_strategy_kind("agent_swarm")
    assert exc_info.value.code == "execution_strategy_invalid"


def test_specialist_role_definition_rejects_unknown_role() -> None:
    with pytest.raises(ProblemError) as exc_info:
        specialist_role_definition("not_a_real_role")
    assert exc_info.value.code == "agent_role_unknown"


def test_router_selects_only_matching_specialists() -> None:
    decision = Router().route(
        objective="Investigate why the deployment broke.",
        specialists=[
            ("dep", "deployment_specialist"),
            ("cust", "customer_impact_specialist"),
        ],
        objective_hash="hash",
    )
    assert decision.selected_step_keys == {"dep"}
    assert decision.skipped_step_keys == {"cust"}
    assert decision.fallback_selected_all is False


def test_router_falls_back_to_all_when_nothing_matches() -> None:
    decision = Router().route(
        objective="Please look into this generically.",
        specialists=[
            ("dep", "deployment_specialist"),
            ("cust", "customer_impact_specialist"),
        ],
        objective_hash="hash",
    )
    assert decision.selected_step_keys == {"dep", "cust"}
    assert decision.fallback_selected_all is True


def test_router_is_deterministic_for_the_same_objective() -> None:
    specialists = [("dep", "deployment_specialist"), ("cust", "customer_impact_specialist")]
    first = Router().route(objective="deploy issue", specialists=specialists, objective_hash="h")
    second = Router().route(objective="deploy issue", specialists=specialists, objective_hash="h")
    assert first.selected_step_keys == second.selected_step_keys


def test_router_rejects_unknown_role_in_specialist_list() -> None:
    with pytest.raises(ProblemError):
        Router().route(
            objective="deploy",
            specialists=[("bad", "not_a_real_role")],
            objective_hash="h",
        )


def test_specialist_catalog_is_within_bounds() -> None:
    from forge_api.domain.multi_agent import SPECIALIST_ROLES

    assert len(SPECIALIST_ROLES) <= MAX_SPECIALISTS
    assert len({role.role for role in SPECIALIST_ROLES}) == len(SPECIALIST_ROLES)


def test_parse_specialist_result_accepts_well_formed_payload() -> None:
    payload = {
        "step_key": "dep",
        "role": "deployment_specialist",
        "outcome": "succeeded",
        "summary": "ok",
        "citations": [],
        "termination_reason": "completed",
        "iterations": 1,
        "tool_calls_used": 1,
        "model_calls_used": 1,
    }
    result = parse_specialist_result(payload)
    assert result is not None
    assert result.outcome == SpecialistOutcome.SUCCEEDED


def test_parse_specialist_result_tolerates_unexpected_shape() -> None:
    assert parse_specialist_result({"mode": "multi_agent_synthesis"}) is None
    assert parse_specialist_result("not-a-dict") is None
    assert parse_specialist_result(None) is None


def test_synthesis_result_requires_at_least_one_specialist_result() -> None:
    synthesis = SynthesisResult(
        overall_status="succeeded",
        partial_failure=False,
        specialist_results=[],
        synthesized_summary="empty",
        citations=[],
    )
    assert synthesis.specialist_results == []
