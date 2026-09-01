from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from forge_api.api.dependencies import (
    get_actor,
    get_database,
    get_settings,
    require_idempotency_key,
)
from forge_api.application.planning_service import PlannerService
from forge_api.config import Settings
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database

router = APIRouter(prefix="/v1/runs", tags=["planning"])


class RunPlanningRequest(BaseModel):
    provider: Literal["fake", "langchain_fake", "openai_compatible"] = "fake"
    fake_scenario: Literal[
        "valid",
        "repairable_malformed",
        "hallucinated_tool",
        "cyclic_plan",
        "refusal",
        "prompt_injection",
    ] = "valid"
    allow_correction: bool = True
    objective_hint: str = Field(default="Plan this run.", min_length=2, max_length=500)


@router.post("/{run_id}:plan", status_code=201)
def plan_run(
    run_id: str,
    payload: RunPlanningRequest,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_settings)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, object]:
    return PlannerService(database, settings).plan_run(
        actor,
        run_id,
        idempotency_key,
        payload.model_dump(),
    )


@router.get("/{run_id}/plans")
def list_plans(
    run_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    return {"plans": PlannerService(database, settings).list_plans(actor, run_id)}


@router.get("/{run_id}/model-calls")
def list_model_calls(
    run_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    return {"model_calls": PlannerService(database, settings).list_model_calls(actor, run_id)}
