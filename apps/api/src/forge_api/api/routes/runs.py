from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from forge_api.api.dependencies import get_actor, get_database, require_idempotency_key
from forge_api.application.run_service import RunService
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database

router = APIRouter(prefix="/v1/runs", tags=["runs"])


class RunCreateRequest(BaseModel):
    workspace_id: str
    workflow_version_id: str
    objective: str = Field(min_length=2, max_length=4096)
    constraints: dict[str, Any] = Field(default_factory=dict)
    engine_kind: Literal["custom", "langgraph"] = "custom"
    strategy_kind: Literal["single_agentic", "multi_agent_parallel"] = "single_agentic"


class RunCancelRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


@router.get("")
def list_runs(
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"runs": RunService(database).list_runs(actor)}


@router.post("", status_code=201)
def create_run(
    payload: RunCreateRequest,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, object]:
    return RunService(database).create(
        actor,
        idempotency_key,
        payload.model_dump(),
    )


@router.get("/{run_id}")
def get_run(
    run_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"run": RunService(database).get(actor, run_id)}


@router.get("/{run_id}/tasks")
def list_tasks(
    run_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"tasks": RunService(database).list_tasks(actor, run_id)}


@router.get("/{run_id}/events")
def list_events(
    run_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"events": RunService(database).list_events(actor, run_id)}


@router.post("/{run_id}:cancel")
def cancel_run(
    run_id: str,
    payload: RunCancelRequest,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"run": RunService(database).cancel(actor, run_id, payload.reason)}


@router.post("/{run_id}:advance")
def advance_run(
    run_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"run": RunService(database).advance_one_ready_task(actor, run_id)}
