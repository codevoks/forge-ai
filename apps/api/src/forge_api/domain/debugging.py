from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

EVENT_SCHEMA_VERSION = 1


class ReplayMode(StrEnum):
    SIMULATION = "simulation"
    EFFECT_REPLAY = "effect_replay"


class ReplayStatus(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"
    FAILED = "failed"


class ProjectionStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class TraceExportStatus(StrEnum):
    LOCAL_ARTIFACT = "local_artifact"
    DISABLED = "disabled"
    BLOCKED = "blocked"
    FAILED = "failed"


class DebugEventSchema(BaseModel):
    event_type: str
    schema_version: int = EVENT_SCHEMA_VERSION
    category: str
    description: str
    authoritative_for_projection: bool = True
    payload_contract: dict[str, str] = Field(default_factory=dict)


EVENT_CATALOG: dict[str, DebugEventSchema] = {
    "run.created": DebugEventSchema(
        event_type="run.created",
        category="run",
        description="Run and objective snapshot were created.",
        payload_contract={"workflow_version_id": "uuid", "objective_id": "uuid"},
    ),
    "run.running": DebugEventSchema(
        event_type="run.running",
        category="run",
        description="Run moved from created to running.",
    ),
    "run.succeeded": DebugEventSchema(
        event_type="run.succeeded",
        category="run",
        description="Run reached succeeded terminal state.",
        payload_contract={"completed_tasks": "integer"},
    ),
    "run.failed": DebugEventSchema(
        event_type="run.failed",
        category="run",
        description="Run reached failed terminal state.",
    ),
    "run.cancelled": DebugEventSchema(
        event_type="run.cancelled",
        category="run",
        description="Run reached cancelled terminal state.",
    ),
    "task.ready": DebugEventSchema(
        event_type="task.ready",
        category="task",
        description="Task dependencies were satisfied and task became executable.",
    ),
    "task.claimed": DebugEventSchema(
        event_type="task.claimed",
        category="task",
        description="Worker claimed a task with a lease/fencing token.",
    ),
    "task.trace_correlated": DebugEventSchema(
        event_type="task.trace_correlated",
        category="task",
        description=(
            "A real OTel W3C trace context was captured for this task attempt, "
            "continuing the run's root trace when the enqueued work carried one."
        ),
        authoritative_for_projection=False,
        payload_contract={"span_name": "string"},
    ),
    "task.succeeded": DebugEventSchema(
        event_type="task.succeeded",
        category="task",
        description="Task attempt succeeded and the task projection was updated.",
    ),
    "task.failed": DebugEventSchema(
        event_type="task.failed",
        category="task",
        description="Task failed safely.",
    ),
    "task.retry_scheduled": DebugEventSchema(
        event_type="task.retry_scheduled",
        category="task",
        description="Retryable failure scheduled a future attempt.",
    ),
    "task.waiting_approval": DebugEventSchema(
        event_type="task.waiting_approval",
        category="approval",
        description="Task stopped before a high-risk effect pending exact-action approval.",
    ),
    "approval.requested": DebugEventSchema(
        event_type="approval.requested",
        category="approval",
        description="Exact-action approval request was persisted.",
    ),
    "approval.approved": DebugEventSchema(
        event_type="approval.approved",
        category="approval",
        description="Eligible approver approved an exact pending action.",
    ),
    "approval.rejected": DebugEventSchema(
        event_type="approval.rejected",
        category="approval",
        description="Approval request was rejected and failed closed.",
    ),
    "approval.expired": DebugEventSchema(
        event_type="approval.expired",
        category="approval",
        description="Approval request expired and failed closed.",
    ),
    "agent.iteration_recorded": DebugEventSchema(
        event_type="agent.iteration_recorded",
        category="agent",
        description="Bounded agent decision evidence was recorded.",
    ),
    "plan.validated": DebugEventSchema(
        event_type="plan.validated",
        category="planning",
        description="Structured model plan passed Forge validation.",
    ),
    "plan.rejected": DebugEventSchema(
        event_type="plan.rejected",
        category="planning",
        description="Structured model plan was rejected by Forge validation.",
    ),
    "dead_letter.requeued": DebugEventSchema(
        event_type="dead_letter.requeued",
        category="recovery",
        description="Operator requeued a sanitized dead letter.",
    ),
}


PROJECTION_TERMINAL_RUN_EVENTS = {
    "run.succeeded": "succeeded",
    "run.failed": "failed",
    "run.cancelled": "cancelled",
}

PROJECTION_TERMINAL_TASK_EVENTS = {
    "task.succeeded": "succeeded",
    "task.failed": "failed",
    "task.waiting_approval": "waiting_approval",
}


def event_catalog_payload() -> list[dict[str, Any]]:
    return [
        schema.model_dump(mode="json")
        for schema in sorted(EVENT_CATALOG.values(), key=lambda item: item.event_type)
    ]
