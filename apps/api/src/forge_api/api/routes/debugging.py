from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from forge_api.api.dependencies import get_actor, get_database, require_idempotency_key
from forge_api.application.debugging_service import DebuggingService
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database

router = APIRouter(prefix="/v1/runs", tags=["debugging"])


class ReplayCreateRequest(BaseModel):
    mode: Literal["simulation", "effect_replay"] = "simulation"


class TraceExportCreateRequest(BaseModel):
    exporter: Literal["local", "langsmith"] = "local"
    mode: Literal["local", "disabled", "enabled"] = "local"


@router.get("/{run_id}/debugger")
def get_debugger(
    run_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"debugger": DebuggingService(database).get_debugger(actor, run_id)}


@router.get("/{run_id}/debugger/events")
def get_debug_event_feed(
    run_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, object]:
    return {
        "timeline": DebuggingService(database).event_feed(
            actor,
            run_id,
            cursor=cursor,
            limit=limit,
        )
    }


@router.post("/{run_id}/debugger/projection-verifications", status_code=201)
def verify_projection(
    run_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, object]:
    return DebuggingService(database).verify_projection(actor, run_id, idempotency_key)


@router.post("/{run_id}/debugger/replays", status_code=201)
def create_replay(
    run_id: str,
    payload: ReplayCreateRequest,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, object]:
    return DebuggingService(database).create_replay(
        actor,
        run_id,
        mode=payload.mode,
        idempotency_key=idempotency_key,
    )


@router.post("/{run_id}/debugger/trace-exports", status_code=201)
def create_trace_export(
    run_id: str,
    payload: TraceExportCreateRequest,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, object]:
    return DebuggingService(database).create_trace_export(
        actor,
        run_id,
        exporter=payload.exporter,
        mode=payload.mode,
        idempotency_key=idempotency_key,
    )
