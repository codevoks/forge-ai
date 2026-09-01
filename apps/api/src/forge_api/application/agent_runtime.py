import json
import operator
from typing import Annotated, Any, Literal, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Interrupt

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
from forge_api.domain.approvals import ApprovalRequiredError
from forge_api.infrastructure.agent_repositories import (
    AgentPromptRepository,
    AgentRepository,
)
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.engine_repositories import WorkflowEngineCheckpointRepository
from forge_api.infrastructure.workflow_repositories import EventRepository

# Deterministic default arguments per code-registered tool, used only for the
# fake model's routine "collect evidence with my first granted tool" branch.
_DEFAULT_TOOL_ARGUMENTS: dict[str, dict[str, object]] = {
    "deployment_history.lookup": {"service": "api", "environment": "production"},
    "customer_reports.search": {"product_area": "worker", "severity": "medium"},
}


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
        if scenario == AgentScenario.APPROVAL_INTERRUPT and not state.evidence:
            return json.dumps(
                {
                    "decision": "tool_call",
                    "rationale": "Request the existing high-risk local simulated effect.",
                    "tool_call": {
                        "tool_name": "ticket.create_simulated",
                        "tool_version": 1,
                        "arguments": {
                            "title": "Review bounded LangGraph agent result",
                            "severity": "medium",
                            "dry_run": True,
                            "simulate_outcome_unknown": False,
                        },
                    },
                }
            )
        if not state.evidence:
            # Pick the task's own first granted tool rather than a hardcoded
            # name: a single-agent Phase 7 task and an isolated Phase 12
            # specialist both reach this branch, and each must collect
            # evidence using only the tool it was actually scoped to.
            tool = state.allowed_tools[0]
            arguments = _DEFAULT_TOOL_ARGUMENTS.get(
                tool.tool_name, {"service": "api", "environment": "production"}
            )
            return json.dumps(
                {
                    "decision": "tool_call",
                    "rationale": "Collect deterministic evidence before concluding.",
                    "tool_call": {
                        "tool_name": tool.tool_name,
                        "tool_version": tool.tool_version,
                        "arguments": arguments,
                    },
                }
            )
        return json.dumps(
            {
                "decision": "complete",
                "rationale": "Use persisted evidence to produce a cited result.",
                "completion": {
                    "summary": (
                        "Local deterministic evidence was collected and no unsafe external "
                        "provider call was needed. The conclusion is grounded in the cited "
                        "evidence."
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
                task_id=str(claim["task_id"]),
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


class LangGraphRuntimeState(TypedDict, total=False):
    claim: dict[str, Any]
    agent_input: Any
    agent_state: AgentState
    prompt: dict[str, Any]
    raw_output: str
    decision: AgentDecision
    validation_errors: list[str]
    iteration: dict[str, Any]
    route: Literal["decide", "tool", "complete", "fail"]
    terminal_result: dict[str, Any]
    failure_reason: AgentTerminationReason
    failure_message: str
    graph_history: Annotated[list[str], operator.add]


class ForgeLangGraphCheckpointer(InMemorySaver):
    def __init__(self, *, database: Database) -> None:
        super().__init__()
        self.database = database

    def put(
        self,
        config: Any,
        checkpoint: Any,
        metadata: Any,
        new_versions: Any,
    ) -> Any:
        next_config = super().put(config, checkpoint, metadata, new_versions)
        config_payload = config if isinstance(config, dict) else {}
        checkpoint_payload = checkpoint if isinstance(checkpoint, dict) else {}
        metadata_payload = metadata if isinstance(metadata, dict) else {}
        configurable = dict(config_payload.get("configurable", {}))
        tenant_id = configurable.get("tenant_id")
        workspace_id = configurable.get("workspace_id")
        run_id = configurable.get("run_id")
        if not tenant_id or not workspace_id or not run_id:
            return next_config

        task_id = configurable.get("task_id")
        attempt_id = configurable.get("attempt_id")
        channel_values = checkpoint_payload.get("channel_values", {})
        if not isinstance(channel_values, dict):
            channel_values = {}
        last_node = _last_graph_node(metadata_payload)
        state_summary = _summarize_langgraph_channels(channel_values)
        next_configurable = (
            next_config.get("configurable", {}) if isinstance(next_config, dict) else {}
        )
        checkpoint_identifier = str(
            checkpoint_payload.get("id")
            or next_configurable.get("checkpoint_id")
            or f"checkpoint-{len(state_summary.get('channel_keys', []))}"
        )
        with self.database.transaction(worker_id="forge-langgraph-checkpointer") as conn:
            WorkflowEngineCheckpointRepository(conn).record_checkpoint(
                tenant_id=str(tenant_id),
                workspace_id=str(workspace_id),
                run_id=str(run_id),
                task_id=str(task_id) if task_id else None,
                attempt_id=str(attempt_id) if attempt_id else None,
                engine_kind="langgraph",
                engine_version=str(configurable.get("engine_version", "langgraph-stategraph-v1")),
                namespace=str(configurable.get("checkpoint_ns") or "agent-runtime"),
                checkpoint_id=checkpoint_identifier,
                node_name=last_node,
                state_summary=state_summary,
                metadata={
                    "langgraph_source": metadata_payload.get("source"),
                    "langgraph_step": metadata_payload.get("step"),
                    "writes": sorted((metadata_payload.get("writes") or {}).keys())
                    if isinstance(metadata_payload.get("writes"), dict)
                    else [],
                },
            )
        return next_config


class LangGraphAgentRuntime(AgentRuntime):
    def __init__(self, *, database: Database) -> None:
        super().__init__(database=database)
        self.checkpointer = ForgeLangGraphCheckpointer(database=database)
        self.graph = self._compile_graph()

    def invoke_for_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        task_input = claim.get("input", {})
        if not isinstance(task_input, dict):
            raise ProblemError(422, "agent_task_invalid", "Agent task input must be an object.")
        agent_input = parse_agent_task_input(task_input)
        config = {
            "configurable": {
                "thread_id": f"{claim['tenant_id']}:{claim['run_id']}:{claim['task_id']}",
                "checkpoint_ns": "agent-runtime",
                "tenant_id": str(claim["tenant_id"]),
                "workspace_id": str(claim["workspace_id"]),
                "run_id": str(claim["run_id"]),
                "task_id": str(claim["task_id"]),
                "attempt_id": str(claim["attempt_id"]),
                "engine_version": str(claim.get("engine_version", "langgraph-stategraph-v1")),
            }
        }
        result = self.graph.invoke(
            {"claim": claim, "agent_input": agent_input, "graph_history": []},
            config=config,
        )
        terminal = result.get("terminal_result")
        if isinstance(terminal, dict):
            return terminal | {
                "workflow_engine": "langgraph",
                "engine_version": str(claim.get("engine_version", "langgraph-stategraph-v1")),
                "langgraph_nodes": result.get("graph_history", []),
            }
        reason = result.get("failure_reason")
        message = result.get("failure_message")
        if isinstance(reason, AgentTerminationReason) and isinstance(message, str):
            self._raise_termination(reason, message)
        raise ProblemError(500, "langgraph_result_invalid", "LangGraph agent did not terminate.")

    def _compile_graph(self) -> Any:
        graph: StateGraph[LangGraphRuntimeState] = StateGraph(LangGraphRuntimeState)
        graph.add_node("load_state", self._load_state_node)
        graph.add_node("decide", self._decide_node)
        graph.add_node("validate_and_record", self._validate_and_record_node)
        graph.add_node("tool_node", self._tool_node)
        graph.add_node("complete_node", self._complete_node)
        graph.add_node("fail_node", self._fail_node)
        graph.add_edge(START, "load_state")
        graph.add_conditional_edges(
            "load_state",
            self._route_after_load,
            {"decide": "decide", "fail": "fail_node"},
        )
        graph.add_edge("decide", "validate_and_record")
        graph.add_conditional_edges(
            "validate_and_record",
            self._route_after_record,
            {
                "decide": "load_state",
                "tool": "tool_node",
                "complete": "complete_node",
                "fail": "fail_node",
            },
        )
        graph.add_edge("tool_node", "load_state")
        graph.add_edge("complete_node", END)
        graph.add_edge("fail_node", END)
        return graph.compile(checkpointer=self.checkpointer)

    def _load_state_node(self, state: LangGraphRuntimeState) -> LangGraphRuntimeState:
        claim = state["claim"]
        agent_input = state["agent_input"]
        agent_state, prompt = self._build_state(claim=claim, agent_input=agent_input)
        self._record_engine_boundary(
            claim=claim,
            node_name="load_state",
            checkpoint_id=f"load-{agent_state.iteration_number}",
            state_summary={
                "iteration_number": agent_state.iteration_number,
                "tool_calls_used": agent_state.tool_calls_used,
                "model_calls_used": agent_state.model_calls_used,
                "evidence_items": len(agent_state.evidence),
                "allowed_tool_count": len(agent_state.allowed_tools),
            },
            metadata={"source": "explicit_langgraph_node"},
        )
        terminated = self.termination.pre_decision(agent_state)
        if terminated is not None:
            return {
                "agent_state": agent_state,
                "prompt": prompt,
                "route": "fail",
                "failure_reason": terminated,
                "failure_message": f"Agent stopped safely: {terminated.value}.",
                "graph_history": ["load_state"],
            }
        return {
            "agent_state": agent_state,
            "prompt": prompt,
            "route": "decide",
            "graph_history": ["load_state"],
        }

    def _decide_node(self, state: LangGraphRuntimeState) -> LangGraphRuntimeState:
        agent_state = state["agent_state"]
        raw_output = self.model.decide(state=agent_state, scenario=state["agent_input"].scenario)
        try:
            decision = parse_agent_decision(raw_output)
            validation_errors = self.validator.validate(decision=decision, state=agent_state)
        except ProblemError as exc:
            decision = AgentDecision(
                decision=AgentDecisionType.FAIL,
                rationale="The model returned invalid structure.",
                failure=FailurePayload(reason=exc.message),
            )
            validation_errors = [exc.message]
        self._record_engine_boundary(
            claim=state["claim"],
            node_name="decide",
            checkpoint_id=f"decide-{agent_state.iteration_number}",
            state_summary={
                "iteration_number": agent_state.iteration_number,
                "decision_type": decision.decision.value,
                "validation_error_count": len(validation_errors),
            },
            metadata={"source": "explicit_langgraph_node"},
        )
        return {
            "raw_output": raw_output,
            "decision": decision,
            "validation_errors": validation_errors,
            "graph_history": ["decide"],
        }

    def _validate_and_record_node(self, state: LangGraphRuntimeState) -> LangGraphRuntimeState:
        claim = state["claim"]
        prompt = state["prompt"]
        agent_state = state["agent_state"]
        decision = state["decision"]
        raw_output = state["raw_output"]
        validation_errors = state.get("validation_errors", [])
        status = (
            AgentDecisionStatus.REJECTED
            if validation_errors
            else AgentDecisionStatus.VALIDATED
        )
        iteration = self._record_iteration(
            claim=claim,
            prompt_version_id=str(prompt["id"]),
            state=agent_state,
            raw_output=raw_output,
            decision=decision,
            status=status,
            validation_errors=validation_errors,
            result={
                "engine": "langgraph",
                "node": "validate_and_record",
                "errors": validation_errors,
            }
            if validation_errors
            else {"engine": "langgraph", "node": "validate_and_record"},
        )
        self._record_engine_boundary(
            claim=claim,
            node_name="validate_and_record",
            checkpoint_id=f"validate-{iteration['iteration_number']}",
            state_summary={
                "agent_iteration_id": iteration["id"],
                "iteration_number": iteration["iteration_number"],
                "decision_type": decision.decision.value,
                "decision_status": status.value,
                "validation_error_count": len(validation_errors),
            },
            metadata={"source": "explicit_langgraph_node"},
        )
        if validation_errors:
            next_state, _ = self._build_state(claim=claim, agent_input=state["agent_input"])
            reason = self.termination.rejection_reason(next_state)
            if reason is not None:
                return {
                    "iteration": iteration,
                    "route": "fail",
                    "failure_reason": reason,
                    "failure_message": (
                        "Agent stopped after repeated invalid or no-progress decisions."
                    ),
                    "graph_history": ["validate_and_record"],
                }
            return {
                "iteration": iteration,
                "route": "decide",
                "graph_history": ["validate_and_record"],
            }
        if decision.decision == AgentDecisionType.COMPLETE:
            return {
                "iteration": iteration,
                "route": "complete",
                "graph_history": ["validate_and_record"],
            }
        if decision.decision == AgentDecisionType.FAIL:
            return {
                "iteration": iteration,
                "route": "fail",
                "failure_reason": AgentTerminationReason.FAILED,
                "failure_message": decision.failure.reason if decision.failure else "Agent failed.",
                "graph_history": ["validate_and_record"],
            }
        if decision.decision == AgentDecisionType.REQUEST_REPLAN:
            return {
                "iteration": iteration,
                "route": "fail",
                "failure_reason": AgentTerminationReason.REPLAN_NOT_AVAILABLE,
                "failure_message": (
                    "Replan lineage is recorded, but execution-time replanning is deferred."
                ),
                "graph_history": ["validate_and_record"],
            }
        return {
            "iteration": iteration,
            "route": "tool",
            "graph_history": ["validate_and_record"],
        }

    def _tool_node(self, state: LangGraphRuntimeState) -> LangGraphRuntimeState:
        claim = state["claim"]
        decision = state["decision"]
        iteration = state["iteration"]
        if decision.tool_call is None:
            raise ProblemError(422, "agent_tool_call_missing", "Tool decision is missing payload.")
        try:
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
        except ApprovalRequiredError as exc:
            interrupt_marker = Interrupt(
                value={
                    "approval_request_id": exc.approval_request_id,
                    "reason": "Forge exact-action approval required before tool execution.",
                },
                id=f"approval-{iteration['id']}",
            )
            self._record_engine_boundary(
                claim=claim,
                node_name="approval_interrupt",
                checkpoint_id=f"approval-{iteration['id']}",
                state_summary={
                    "decision_type": "tool_call",
                    "tool_name": decision.tool_call.tool_name,
                    "approval_interrupt": True,
                },
                metadata={
                    "interrupt_id": interrupt_marker.id,
                    "interrupt_value": interrupt_marker.value,
                },
            )
            raise
        self._mark_tool_observed(iteration_id=str(iteration["id"]), tool_result=tool_result)
        self._record_engine_boundary(
            claim=claim,
            node_name="tool_node",
            checkpoint_id=f"tool-{iteration['id']}",
            state_summary={
                "agent_iteration_id": iteration["id"],
                "tool_name": tool_result.get("tool_name"),
                "tool_version": tool_result.get("tool_version"),
                "evidence_recorded": isinstance(tool_result.get("evidence"), dict),
            },
            metadata={"source": "explicit_langgraph_node"},
        )
        return {"route": "decide", "graph_history": ["tool_node"]}

    def _complete_node(self, state: LangGraphRuntimeState) -> LangGraphRuntimeState:
        decision = state["decision"]
        iteration = state["iteration"]
        if decision.completion is None:
            raise ProblemError(422, "agent_completion_missing", "Completion is missing payload.")
        self._record_engine_boundary(
            claim=state["claim"],
            node_name="complete_node",
            checkpoint_id=f"complete-{iteration['id']}",
            state_summary={
                "agent_iteration_id": iteration["id"],
                "iteration_number": iteration["iteration_number"],
                "citation_count": len(decision.completion.citations),
            },
            metadata={"source": "explicit_langgraph_node"},
        )
        return {
            "terminal_result": {
                "mode": "bounded_agent",
                "status": "succeeded",
                "termination_reason": AgentTerminationReason.COMPLETED.value,
                "summary": decision.completion.summary,
                "citations": decision.completion.citations,
                "iterations": iteration["iteration_number"],
                "paid_provider_calls": 0,
            },
            "graph_history": ["complete_node"],
        }

    def _fail_node(self, state: LangGraphRuntimeState) -> LangGraphRuntimeState:
        reason = state.get("failure_reason", AgentTerminationReason.FAILED)
        message = state.get("failure_message", "Agent failed closed.")
        claim = state.get("claim")
        if isinstance(claim, dict):
            self._record_engine_boundary(
                claim=claim,
                node_name="fail_node",
                checkpoint_id=f"fail-{claim['attempt_id']}",
                state_summary={
                    "termination_reason": reason.value,
                    "safe_failure": True,
                },
                metadata={"source": "explicit_langgraph_node", "message": message},
            )
        return {
            "failure_reason": reason,
            "failure_message": message,
            "graph_history": ["fail_node"],
        }

    def _route_after_load(self, state: LangGraphRuntimeState) -> str:
        return state.get("route", "decide")

    def _route_after_record(self, state: LangGraphRuntimeState) -> str:
        return state.get("route", "fail")

    def _record_engine_boundary(
        self,
        *,
        claim: dict[str, Any],
        node_name: str,
        checkpoint_id: str,
        state_summary: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        with self.database.transaction(worker_id="forge-langgraph-runtime") as conn:
            WorkflowEngineCheckpointRepository(conn).record_checkpoint(
                tenant_id=str(claim["tenant_id"]),
                workspace_id=str(claim["workspace_id"]),
                run_id=str(claim["run_id"]),
                task_id=str(claim["task_id"]),
                attempt_id=str(claim["attempt_id"]),
                engine_kind="langgraph",
                engine_version=str(claim.get("engine_version", "langgraph-stategraph-v1")),
                namespace="agent-runtime",
                checkpoint_id=checkpoint_id,
                node_name=node_name,
                state_summary=state_summary,
                metadata=metadata,
            )


def _last_graph_node(metadata: dict[str, Any]) -> str:
    writes = metadata.get("writes")
    if isinstance(writes, dict) and writes:
        return str(next(iter(writes.keys())))
    source = metadata.get("source")
    if source:
        return str(source)
    return "langgraph_checkpoint"


def _summarize_langgraph_channels(channel_values: dict[str, Any]) -> dict[str, Any]:
    decision = channel_values.get("decision")
    agent_state = channel_values.get("agent_state")
    iteration = channel_values.get("iteration")
    graph_history = channel_values.get("graph_history")
    summary: dict[str, Any] = {
        "channel_keys": sorted(str(key) for key in channel_values.keys()),
        "has_claim_reference": "claim" in channel_values,
        "has_agent_state": isinstance(agent_state, AgentState),
        "history_length": len(graph_history) if isinstance(graph_history, list) else 0,
    }
    if isinstance(decision, AgentDecision):
        summary["decision_type"] = decision.decision.value
    if isinstance(agent_state, AgentState):
        summary["iteration_number"] = agent_state.iteration_number
        summary["tool_calls_used"] = agent_state.tool_calls_used
        summary["model_calls_used"] = agent_state.model_calls_used
        summary["evidence_items"] = len(agent_state.evidence)
        summary["allowed_tool_count"] = len(agent_state.allowed_tools)
    if isinstance(iteration, dict):
        summary["agent_iteration_id"] = iteration.get("id")
        summary["recorded_iteration_number"] = iteration.get("iteration_number")
    return summary
