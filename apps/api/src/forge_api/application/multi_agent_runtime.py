from typing import Any

from forge_api.api.errors import ProblemError
from forge_api.application.agent_runtime import AgentRuntime
from forge_api.domain.agent import AgentTerminationReason
from forge_api.domain.multi_agent import (
    SpecialistOutcome,
    SpecialistResult,
    SynthesisResult,
    parse_specialist_result,
)
from forge_api.infrastructure.agent_repositories import AgentRepository
from forge_api.infrastructure.database import Database

_SAFE_TERMINATION_CODES = {
    reason.value for reason in AgentTerminationReason if reason != AgentTerminationReason.COMPLETED
}


class SpecialistAgentRuntime(AgentRuntime):
    """Runs one isolated specialist inside its own bounded-agent task.

    Reuses `AgentRuntime`'s entire decision loop, budgets, and validation
    unchanged. The only difference: a safe termination (step/tool/model
    budget exhausted, repeated invalid decisions, or the model explicitly
    giving up) is durable-task-level *success* carrying a soft
    `SpecialistOutcome.SAFE_FAILURE` result, not a task failure. This lets the
    synthesizer produce a partial result from the specialists that did
    succeed instead of the whole run failing because one specialist could not
    reach a conclusion. A genuine infrastructure failure (for example the
    worker crashing) is not caught here and still fails the task/run through
    the unchanged Phase 3 durable-execution path — only agent-reasoning
    limits are treated as soft.
    """

    def invoke_for_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        task_input = claim.get("input", {})
        role = (
            str(task_input.get("agent_role"))
            if isinstance(task_input, dict) and task_input.get("agent_role")
            else str(claim.get("step_key", "unknown"))
        )
        step_key = str(claim.get("step_key", ""))
        task_id = str(claim["task_id"])

        try:
            raw_result = super().invoke_for_claim(claim)
        except ProblemError as exc:
            if exc.code not in _SAFE_TERMINATION_CODES:
                raise
            counters = self._counters(task_id)
            specialist = SpecialistResult(
                step_key=step_key,
                role=role,
                outcome=SpecialistOutcome.SAFE_FAILURE,
                summary="",
                citations=[],
                termination_reason=exc.code,
                iterations=counters["model_calls_used"],
                tool_calls_used=counters["tool_calls_used"],
                model_calls_used=counters["model_calls_used"],
            )
            return specialist.model_dump(mode="json")

        counters = self._counters(task_id)
        specialist = SpecialistResult(
            step_key=step_key,
            role=role,
            outcome=SpecialistOutcome.SUCCEEDED,
            summary=str(raw_result.get("summary", "")),
            citations=[str(item) for item in raw_result.get("citations", [])],
            termination_reason=str(raw_result.get("termination_reason", "completed")),
            iterations=int(raw_result.get("iterations", counters["model_calls_used"])),
            tool_calls_used=counters["tool_calls_used"],
            model_calls_used=counters["model_calls_used"],
        )
        return specialist.model_dump(mode="json")

    def _counters(self, task_id: str) -> dict[str, int]:
        with self.database.transaction(worker_id="forge-multi-agent-runtime") as conn:
            repo = AgentRepository(conn)
            return {
                "model_calls_used": repo.count_model_calls(task_id=task_id),
                "tool_calls_used": repo.count_tool_calls(task_id=task_id),
            }


class SynthesizerRuntime:
    """Deterministic aggregator: never a model call.

    Reads immutable prerequisite specialist task results (`tasks.result`, the
    same durable storage every task result already uses) through the
    existing DAG dependency edges, so aggregation provenance is exactly the
    run's own task graph — no parallel "handoff" storage. Aggregation is
    plain code over already-validated `SpecialistResult` payloads, which
    structurally prevents the "synthesizer fabricates consensus" failure
    mode: there is no free-text model step that could invent an agreement
    the specialists never reached.
    """

    def __init__(self, *, database: Database) -> None:
        self.database = database

    def invoke_for_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        task_id = str(claim["task_id"])
        with self.database.transaction(worker_id=str(claim["worker_id"])) as conn:
            prereq_rows = conn.execute(
                """
                select t.step_key, t.status, t.result, t.agent_role
                from task_dependencies d
                join tasks t on t.id = d.from_task_id
                where d.to_task_id = %s
                order by t.step_key
                """,
                (task_id,),
            ).fetchall()

        specialist_results: list[SpecialistResult] = []
        for row in prereq_rows:
            if str(row["status"]) != "succeeded":
                # Defensive only: a genuinely failed prerequisite already
                # fails the whole run via the unchanged Phase 3 fail-fast
                # path before the synthesizer could become ready.
                continue
            parsed = parse_specialist_result(row["result"])
            if parsed is not None:
                specialist_results.append(parsed)

        usable = [r for r in specialist_results if r.outcome == SpecialistOutcome.SUCCEEDED]
        safe_failed_roles = [
            r.role for r in specialist_results if r.outcome == SpecialistOutcome.SAFE_FAILURE
        ]
        if not usable:
            raise ProblemError(
                409,
                "multi_agent_synthesis_no_usable_results",
                "No specialist produced a usable result; synthesis cannot proceed.",
            )

        citations: list[str] = []
        summary_parts: list[str] = []
        for result in usable:
            summary_parts.append(f"[{result.role}] {result.summary}")
            for citation in result.citations:
                if citation not in citations:
                    citations.append(citation)

        synthesis = SynthesisResult(
            overall_status="succeeded",
            partial_failure=bool(safe_failed_roles),
            specialist_results=specialist_results,
            skipped_roles=sorted(set(safe_failed_roles)),
            synthesized_summary=" ".join(summary_parts)[:2000],
            citations=citations[:32],
        )
        return synthesis.model_dump(mode="json")
