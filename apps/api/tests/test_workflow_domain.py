import pytest

from forge_api.api.errors import ProblemError
from forge_api.domain.workflow import (
    TASK_TRANSITIONS,
    DAGValidator,
    TaskStatus,
    WorkflowEdgeDefinition,
    WorkflowStepDefinition,
    validate_transition,
)


def test_dag_validator_accepts_branch_and_join() -> None:
    DAGValidator().validate(
        steps=[
            WorkflowStepDefinition("a", "Step A", "deterministic", {}),
            WorkflowStepDefinition("b", "Step B", "deterministic", {}),
            WorkflowStepDefinition("c", "Step C", "deterministic", {}),
        ],
        edges=[
            WorkflowEdgeDefinition("a", "c"),
            WorkflowEdgeDefinition("b", "c"),
        ],
    )


def test_dag_validator_rejects_cycles() -> None:
    with pytest.raises(ProblemError) as exc:
        DAGValidator().validate(
            steps=[
                WorkflowStepDefinition("a", "Step A", "deterministic", {}),
                WorkflowStepDefinition("b", "Step B", "deterministic", {}),
            ],
            edges=[
                WorkflowEdgeDefinition("a", "b"),
                WorkflowEdgeDefinition("b", "a"),
            ],
        )

    assert exc.value.code == "workflow_cycle"


def test_task_transition_rejects_terminal_mutation() -> None:
    with pytest.raises(ProblemError) as exc:
        validate_transition(
            aggregate="task",
            current=TaskStatus.SUCCEEDED.value,
            target=TaskStatus.RUNNING.value,
            table=TASK_TRANSITIONS,
        )

    assert exc.value.code == "invalid_transition"
