from typing import Annotated

from fastapi import APIRouter, Depends

from forge_api.api.dependencies import get_actor, get_database
from forge_api.application.agent_service import AgentService
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database

router = APIRouter(prefix="/v1/runs", tags=["agents"])


@router.get("/{run_id}/agent-iterations")
def list_agent_iterations(
    run_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"agent_iterations": AgentService(database).list_iterations(actor, run_id)}
