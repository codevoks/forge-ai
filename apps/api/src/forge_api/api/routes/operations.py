from typing import Annotated

from fastapi import APIRouter, Depends

from forge_api.api.dependencies import get_actor, get_database, get_settings
from forge_api.application.operations_service import OperationsService
from forge_api.config import Settings
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database

router = APIRouter(prefix="/v1/operations", tags=["operations"])


@router.get("/worker-state")
def worker_state(
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    service = OperationsService(database, worker_id=settings.worker_id)
    return {"worker_state": service.worker_state(actor)}


@router.get("/dead-letters")
def list_dead_letters(
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    service = OperationsService(database, worker_id=settings.worker_id)
    return {"dead_letters": service.list_dead_letters(actor)}


@router.post("/dead-letters/{dead_letter_id}:requeue")
def requeue_dead_letter(
    dead_letter_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    service = OperationsService(database, worker_id=settings.worker_id)
    return {"run": service.requeue_dead_letter(actor, dead_letter_id)}


@router.post("/recovery:scan")
def recovery_scan(
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, object]:
    return {"recovery": OperationsService(database, worker_id=settings.worker_id).recover(actor)}
