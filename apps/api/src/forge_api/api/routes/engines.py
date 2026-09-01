from typing import Annotated

from fastapi import APIRouter, Depends

from forge_api.api.dependencies import get_actor, get_database
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.engine_repositories import WorkflowEngineService

router = APIRouter(prefix="/v1/runs", tags=["workflow-engines"])


@router.get("/{run_id}/engine-checkpoints")
def list_engine_checkpoints(
    run_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"engine_checkpoints": WorkflowEngineService(database).list_checkpoints(actor, run_id)}
