from typing import Annotated

from fastapi import APIRouter, Depends, Query

from forge_api.api.dependencies import get_actor, get_database, require_idempotency_key
from forge_api.application.multi_agent_comparison_service import MultiAgentComparisonService
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database

router = APIRouter(prefix="/v1/multi-agent", tags=["multi-agent"])


@router.post("/comparisons", status_code=201)
def run_comparison(
    workspace_id: Annotated[str, Query(min_length=1)],
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, object]:
    return MultiAgentComparisonService(database).run_comparison(
        actor, workspace_id, idempotency_key
    )


@router.get("/comparisons")
def list_comparisons(
    workspace_id: Annotated[str, Query(min_length=1)],
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    comparisons = MultiAgentComparisonService(database).list_comparisons(actor, workspace_id)
    return {"strategy_comparisons": comparisons}


@router.get("/comparisons/{comparison_id}")
def get_comparison(
    comparison_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"strategy_comparison": MultiAgentComparisonService(database).get(actor, comparison_id)}
