from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from forge_api.api.errors import ProblemError


class WorkflowEngineKind(StrEnum):
    CUSTOM = "custom"
    LANGGRAPH = "langgraph"


ENGINE_VERSIONS: dict[WorkflowEngineKind, str] = {
    WorkflowEngineKind.CUSTOM: "custom-agent-v1",
    WorkflowEngineKind.LANGGRAPH: "langgraph-stategraph-v1",
}


class WorkflowEngineMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_by: str
    zero_cost: bool = True
    live_provider_calls_allowed: bool = False


def parse_workflow_engine_kind(value: str | None) -> WorkflowEngineKind:
    if value is None:
        return WorkflowEngineKind.CUSTOM
    try:
        return WorkflowEngineKind(value)
    except ValueError as exc:
        raise ProblemError(
            422,
            "workflow_engine_invalid",
            "Workflow engine must be one of: custom, langgraph.",
        ) from exc


def engine_version_for(kind: WorkflowEngineKind) -> str:
    return ENGINE_VERSIONS[kind]
