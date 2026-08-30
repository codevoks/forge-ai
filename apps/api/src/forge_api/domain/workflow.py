from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from forge_api.api.errors import ProblemError

MAX_OBJECTIVE_BYTES = 4096
MAX_STEPS = 20
MAX_EDGES = 60
MAX_STEP_KEY_LENGTH = 64
SUPPORTED_STEP_KINDS = frozenset({"manual", "deterministic"})


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_RUN_STATUSES = frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED})
TERMINAL_TASK_STATUSES = frozenset({TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED})


RUN_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.CREATED: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.RUNNING: {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED},
    RunStatus.SUCCEEDED: set(),
    RunStatus.FAILED: set(),
    RunStatus.CANCELLED: set(),
}

TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
    TaskStatus.PENDING: {TaskStatus.READY, TaskStatus.CANCELLED},
    TaskStatus.READY: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED},
    TaskStatus.SUCCEEDED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


@dataclass(frozen=True)
class WorkflowStepDefinition:
    key: str
    name: str
    kind: str
    input: dict[str, Any]


@dataclass(frozen=True)
class WorkflowEdgeDefinition:
    from_key: str
    to_key: str


def validate_payload_size(value: str, *, field: str, max_bytes: int = MAX_OBJECTIVE_BYTES) -> None:
    if len(value.encode("utf-8")) > max_bytes:
        raise ProblemError(422, "payload_too_large", f"{field} exceeds the allowed size.")


def validate_transition(
    *,
    aggregate: str,
    current: str,
    target: str,
    table: dict[Any, set[Any]],
) -> None:
    try:
        current_status = next(status for status in table if status.value == current)
        target_status = next(status for status in table if status.value == target)
    except StopIteration as exc:
        raise ProblemError(
            422, "unsupported_transition_state", "Unsupported transition state."
        ) from exc

    if target_status not in table[current_status]:
        raise ProblemError(
            409,
            "invalid_transition",
            f"{aggregate} cannot transition from {current} to {target}.",
        )


class DAGValidator:
    def validate(
        self,
        *,
        steps: list[WorkflowStepDefinition],
        edges: list[WorkflowEdgeDefinition],
    ) -> None:
        if not steps:
            raise ProblemError(
                422, "workflow_steps_required", "A workflow needs at least one step."
            )
        if len(steps) > MAX_STEPS:
            raise ProblemError(422, "workflow_too_large", "The workflow has too many steps.")
        if len(edges) > MAX_EDGES:
            raise ProblemError(422, "workflow_too_large", "The workflow has too many edges.")

        keys = [step.key for step in steps]
        if len(keys) != len(set(keys)):
            raise ProblemError(422, "duplicate_step_key", "Step keys must be unique.")

        key_set = set(keys)
        for step in steps:
            if not step.key or len(step.key) > MAX_STEP_KEY_LENGTH:
                raise ProblemError(422, "invalid_step_key", "Step keys must be bounded strings.")
            if step.kind not in SUPPORTED_STEP_KINDS:
                raise ProblemError(
                    422, "unsupported_step_kind", "The workflow contains an unsupported step kind."
                )

        seen_edges: set[tuple[str, str]] = set()
        adjacency: dict[str, list[str]] = {key: [] for key in keys}
        incoming: dict[str, int] = {key: 0 for key in keys}
        for edge in edges:
            if edge.from_key == edge.to_key:
                raise ProblemError(422, "self_dependency", "A step cannot depend on itself.")
            if edge.from_key not in key_set or edge.to_key not in key_set:
                raise ProblemError(
                    422, "missing_edge_endpoint", "Every edge must reference existing steps."
                )
            edge_key = (edge.from_key, edge.to_key)
            if edge_key in seen_edges:
                raise ProblemError(
                    422, "duplicate_edge", "Duplicate workflow edges are not allowed."
                )
            seen_edges.add(edge_key)
            adjacency[edge.from_key].append(edge.to_key)
            incoming[edge.to_key] += 1

        ready = [key for key, count in incoming.items() if count == 0]
        visited = 0
        while ready:
            key = ready.pop()
            visited += 1
            for downstream in adjacency[key]:
                incoming[downstream] -= 1
                if incoming[downstream] == 0:
                    ready.append(downstream)

        if visited != len(steps):
            raise ProblemError(422, "workflow_cycle", "Workflow steps must form an acyclic DAG.")


class ReadinessEvaluator:
    def ready_task_keys(
        self,
        *,
        tasks: list[dict[str, Any]],
        dependencies: list[dict[str, Any]],
    ) -> list[str]:
        task_by_key = {str(task["step_key"]): task for task in tasks}
        ready: list[str] = []
        for step_key, task in task_by_key.items():
            if str(task["status"]) != TaskStatus.PENDING.value:
                continue
            prereqs = [dep for dep in dependencies if str(dep["to_step_key"]) == step_key]
            if all(
                str(task_by_key[str(dep["from_step_key"])]["status"]) == TaskStatus.SUCCEEDED.value
                for dep in prereqs
            ):
                ready.append(step_key)
        return sorted(ready)
