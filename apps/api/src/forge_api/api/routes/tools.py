from typing import Annotated

from fastapi import APIRouter, Depends

from forge_api.api.dependencies import get_actor, get_database
from forge_api.application.tool_service import ToolService
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database

router = APIRouter(prefix="/v1/tools", tags=["tools"])


@router.get("")
def list_tools(
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"tools": ToolService(database).list_tools(actor)}


@router.get("/runs/{run_id}/invocations")
def list_run_tool_invocations(
    run_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"tool_invocations": ToolService(database).list_invocations(actor, run_id)}


@router.get("/runs/{run_id}/evidence")
def list_run_evidence(
    run_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"evidence_items": ToolService(database).list_evidence(actor, run_id)}
