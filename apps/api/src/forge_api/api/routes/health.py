from typing import Annotated

from fastapi import APIRouter, Depends

from forge_api.api.dependencies import get_database, get_settings
from forge_api.config import Settings
from forge_api.infrastructure.database import Database

router = APIRouter(tags=["health"])


@router.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok", "service": "api"}


@router.get("/health/ready")
def ready(
    settings: Annotated[Settings, Depends(get_settings)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    settings.assert_zero_cost_safe()
    return {
        "status": "ok" if database.ping() else "degraded",
        "database": "ok" if database.ping() else "unavailable",
        "external_integrations": settings.external_integrations,
    }
