from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from forge_api.api.dependencies import get_actor, get_database, require_idempotency_key
from forge_api.application.workflow_service import WorkflowService
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])


class WorkflowStepRequest(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=2, max_length=120)
    kind: Literal["manual", "deterministic", "tool"] = "deterministic"
    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowEdgeRequest(BaseModel):
    from_step: str = Field(alias="from", min_length=1, max_length=64)
    to_step: str = Field(alias="to", min_length=1, max_length=64)


class WorkflowCreateRequest(BaseModel):
    workspace_id: str
    name: str = Field(min_length=2, max_length=120)
    steps: list[WorkflowStepRequest] = Field(min_length=1, max_length=20)
    edges: list[WorkflowEdgeRequest] = Field(default_factory=list, max_length=60)


@router.get("")
def list_workflows(
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"workflow_versions": WorkflowService(database).list_versions(actor)}


@router.post("", status_code=201)
def create_workflow(
    payload: WorkflowCreateRequest,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, object]:
    return WorkflowService(database).create_published_version(
        actor,
        idempotency_key,
        payload.model_dump(by_alias=True),
    )


@router.get("/{workflow_version_id}")
def get_workflow(
    workflow_version_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {
        "workflow_version": WorkflowService(database).get_version(
            actor,
            workflow_version_id,
        )
    }
