from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from forge_api.api.dependencies import get_actor, get_database, require_idempotency_key
from forge_api.application.tenant_service import TenantService
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database

router = APIRouter(prefix="/v1/tenants", tags=["tenants"])


class TenantCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    workspace_name: str | None = Field(default=None, min_length=2, max_length=100)


@router.post("", status_code=201)
def create_tenant(
    payload: TenantCreateRequest,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, object]:
    return TenantService(database).create(
        actor,
        idempotency_key,
        payload.model_dump(exclude_none=True),
    )
