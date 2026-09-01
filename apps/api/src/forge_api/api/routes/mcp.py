from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from forge_api.api.dependencies import (
    get_actor,
    get_database,
    require_idempotency_key,
    require_if_match,
)
from forge_api.application.mcp_service import MCPAdminService
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database

router = APIRouter(prefix="/v1/mcp", tags=["mcp"])


class AddServerRequest(BaseModel):
    workspace_id: str
    name: str = Field(min_length=2, max_length=120)
    transport: str
    url: str | None = None
    command: list[str] | None = None
    auth_secret_reference: str | None = None


class EnableMappingRequest(BaseModel):
    forge_tool_name: str = Field(min_length=5, max_length=120)
    risk: str
    expected_schema_hash: str


@router.get("/servers")
def list_servers(
    workspace_id: Annotated[str, Query()],
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"servers": MCPAdminService(database).list_servers(actor, workspace_id)}


@router.post("/servers")
def add_server(
    payload: AddServerRequest,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, object]:
    return MCPAdminService(database).add_server(
        actor,
        workspace_id=payload.workspace_id,
        name=payload.name,
        transport=payload.transport,
        url=payload.url,
        command=payload.command,
        auth_secret_reference=payload.auth_secret_reference,
        idempotency_key=idempotency_key,
    )


@router.get("/servers/{server_id}")
def get_server(
    server_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"server": MCPAdminService(database).get_server(actor, server_id)}


@router.post("/servers/{server_id}:test")
def test_server(
    server_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return MCPAdminService(database).test_server(actor, server_id)


@router.post("/servers/{server_id}:discover")
def discover_server(
    server_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
) -> dict[str, object]:
    return MCPAdminService(database).discover_server(
        actor, server_id, idempotency_key=idempotency_key
    )


@router.post("/servers/{server_id}:disable")
def disable_server(
    server_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Depends(require_if_match)],
) -> dict[str, object]:
    return MCPAdminService(database).disable_server(
        actor, server_id, expected_version=expected_version, idempotency_key=idempotency_key
    )


@router.get("/servers/{server_id}/mappings")
def list_mappings(
    server_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
) -> dict[str, object]:
    return {"mappings": MCPAdminService(database).list_mappings(actor, server_id)}


@router.post("/servers/{server_id}/mappings/{mapping_id}:enable")
def enable_mapping(
    server_id: str,
    mapping_id: str,
    payload: EnableMappingRequest,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Depends(require_if_match)],
) -> dict[str, object]:
    return MCPAdminService(database).enable_mapping(
        actor,
        server_id,
        mapping_id,
        forge_tool_name=payload.forge_tool_name,
        risk=payload.risk,
        expected_schema_hash=payload.expected_schema_hash,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )


@router.post("/servers/{server_id}/mappings/{mapping_id}:disable")
def disable_mapping(
    server_id: str,
    mapping_id: str,
    actor: Annotated[ActorContext, Depends(get_actor)],
    database: Annotated[Database, Depends(get_database)],
    idempotency_key: Annotated[str, Depends(require_idempotency_key)],
    expected_version: Annotated[int, Depends(require_if_match)],
) -> dict[str, object]:
    return MCPAdminService(database).disable_mapping(
        actor,
        server_id,
        mapping_id,
        expected_version=expected_version,
        idempotency_key=idempotency_key,
    )
