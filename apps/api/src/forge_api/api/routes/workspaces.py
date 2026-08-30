from typing import Annotated

from fastapi import APIRouter, Depends

from forge_api.api.dependencies import get_actor, get_database
from forge_api.application.workspace_service import WorkspaceService
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database

router = APIRouter(prefix="/v1/workspaces", tags=["workspaces"])


@router.get("")
def list_workspaces(
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"items": WorkspaceService(database).list_for_actor(actor)}


@router.get("/{workspace_id}")
def get_workspace(
    workspace_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return WorkspaceService(database).get_for_actor(actor, workspace_id)
