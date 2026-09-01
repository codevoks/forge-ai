from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from forge_api.api.dependencies import get_actor, get_database, require_idempotency_key
from forge_api.application.evaluation_service import EvaluationService
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database

router = APIRouter(prefix="/v1/evaluations", tags=["evaluations"])


class EvaluationRunRequest(BaseModel):
    workspace_id: str
    provider_path: Literal["native_and_langchain"] = "native_and_langchain"
    include_langgraph: bool = True
    langsmith_export_mode: Literal["local", "disabled", "enabled"] = "local"


@router.post("", status_code=201)
def create_evaluation_run(
    payload: EvaluationRunRequest,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, Any]:
    return EvaluationService(database).create(actor, idempotency_key, payload.model_dump())


@router.get("")
def list_evaluation_runs(
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    workspace_id: Annotated[str, Query(min_length=1)],
) -> dict[str, Any]:
    return {"evaluation_runs": EvaluationService(database).list_runs(actor, workspace_id)}


@router.get("/{evaluation_run_id}")
def get_evaluation_run(
    evaluation_run_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, Any]:
    return {
        "evaluation_run": EvaluationService(database).get(
            actor,
            evaluation_run_id,
        )
    }
