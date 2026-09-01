from typing import Any

from forge_api.api.errors import ProblemError
from forge_api.domain.agent import stable_hash
from forge_api.domain.multi_agent import MAX_SPECIALISTS, MIN_SPECIALISTS, Router, RoutingDecision


def extract_specialist_steps(workflow_version: dict[str, Any]) -> list[tuple[str, str]]:
    """Specialists are ordinary `kind="agent"` steps whose author-declared
    `input.agent_role` names a code-owned role (see domain/multi_agent.py).
    """
    specialists: list[tuple[str, str]] = []
    for step in workflow_version["steps"]:
        if step["kind"] != "agent":
            continue
        step_input = step["input"]
        role = step_input.get("agent_role") if isinstance(step_input, dict) else None
        if role:
            specialists.append((str(step["key"]), str(role)))
    return specialists


def apply_router(
    *, workflow_version: dict[str, Any], objective: str
) -> tuple[dict[str, Any], RoutingDecision]:
    """Filter a multi-agent workflow's steps/edges to the router-selected specialists.

    The router's proposal is validated and enforced here, in application
    code, before any task is ever persisted: only the resulting *filtered*
    graph is what `RunRepository.create_run` will instantiate. This is the
    Forge authority boundary for delegation — the router (and, if one is
    ever plugged in, a model behind it) never gets to create task authority
    on its own; it only narrows which pre-published, pre-authorized steps
    Forge goes on to instantiate.
    """
    specialists = extract_specialist_steps(workflow_version)
    if len(specialists) < MIN_SPECIALISTS:
        raise ProblemError(
            422,
            "multi_agent_workflow_invalid",
            f"A multi-agent workflow needs at least {MIN_SPECIALISTS} specialist agent steps.",
        )
    if len(specialists) > MAX_SPECIALISTS:
        raise ProblemError(
            422,
            "multi_agent_workflow_invalid",
            f"A multi-agent workflow supports at most {MAX_SPECIALISTS} specialist agent steps.",
        )

    decision = Router().route(
        objective=objective,
        specialists=specialists,
        objective_hash=stable_hash(objective),
    )
    skipped = decision.skipped_step_keys
    filtered_steps = [step for step in workflow_version["steps"] if step["key"] not in skipped]
    filtered_edges = [
        edge
        for edge in workflow_version["edges"]
        if edge["from"] not in skipped and edge["to"] not in skipped
    ]
    filtered = dict(workflow_version)
    filtered["steps"] = filtered_steps
    filtered["edges"] = filtered_edges
    return filtered, decision
