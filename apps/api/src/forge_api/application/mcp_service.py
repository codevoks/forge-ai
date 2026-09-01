from typing import Any

from forge_api.api.errors import ProblemError
from forge_api.application.mcp_tool_adapter import connection_for_server
from forge_api.config import Settings
from forge_api.domain.approvals import FakeSecretResolver
from forge_api.domain.identity import ActorContext, Capability
from forge_api.domain.mcp import (
    MCP_DISCOVERY_TIMEOUT_MS,
    MCPConnectionPolicy,
    MCPTransportKind,
    capability_hash,
    enforce_zero_cost_transport,
)
from forge_api.domain.tools import ToolRisk
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.mcp_repositories import (
    MCPCapabilitySnapshotRepository,
    MCPServerRepository,
    MCPToolMappingRepository,
)
from forge_api.infrastructure.mcp_transport import HttpMCPTransport, StdioMCPTransport
from forge_api.infrastructure.repositories import IdempotencyRepository, canonical_hash
from forge_api.infrastructure.tool_repositories import ToolRegistryRepository
from forge_api.infrastructure.workflow_repositories import WorkflowRepository
from forge_api.policy.authorization import AuthorizationService
from forge_api.ports.mcp import MCPAuthError, MCPClientPort, MCPProtocolViolation, MCPTransportError

FORGE_TOOL_NAME_MAX = 120


def _transport_for(transport: MCPTransportKind) -> MCPClientPort:
    if transport is MCPTransportKind.STDIO:
        return StdioMCPTransport()
    return HttpMCPTransport()


def _idempotent_write(
    conn: Any,
    *,
    scope: str,
    idempotency_key: str,
    request_payload: dict[str, Any],
) -> dict[str, Any] | None:
    idempotency = IdempotencyRepository(conn)
    request_hash = canonical_hash(request_payload)
    existing = idempotency.existing(scope, idempotency_key)
    if existing is None:
        return None
    if existing["request_hash"] != request_hash:
        raise ProblemError(
            409,
            "idempotency_key_reused",
            "The Idempotency-Key was already used with a different request.",
        )
    response_payload = existing["response_payload"]
    if not isinstance(response_payload, dict):
        raise ProblemError(500, "idempotency_record_invalid", "Stored response is invalid.")
    return response_payload


class MCPAdminService:
    def __init__(self, database: Database, settings: Settings | None = None) -> None:
        self.database = database
        self.settings = settings or Settings()

    # -- reads -------------------------------------------------------------

    def list_servers(self, actor: ActorContext, workspace_id: str) -> list[dict[str, Any]]:
        self._resolve_workspace(actor, workspace_id)
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return MCPServerRepository(conn).list_for_actor(
                actor_id=actor.user_id, workspace_id=workspace_id
            )

    def get_server(self, actor: ActorContext, server_id: str) -> dict[str, Any]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            server = MCPServerRepository(conn).get_for_actor(
                actor_id=actor.user_id, server_id=server_id
            )
        self._resolve_workspace(actor, server["workspace_id"])
        return server

    def list_mappings(self, actor: ActorContext, server_id: str) -> list[dict[str, Any]]:
        server = self.get_server(actor, server_id)
        with self.database.transaction(
            tenant_id=server["tenant_id"], actor_id=actor.user_id
        ) as conn:
            return MCPToolMappingRepository(conn).list_for_server(server_id=server_id)

    # -- server lifecycle ---------------------------------------------------

    def add_server(
        self,
        actor: ActorContext,
        *,
        workspace_id: str,
        name: str,
        transport: str,
        url: str | None,
        command: list[str] | None,
        auth_secret_reference: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        scope_row = self._resolve_workspace(actor, workspace_id)
        self._require_admin(actor, workspace_id)
        tenant_id = str(scope_row["tenant_id"])

        connection = MCPConnectionPolicy().validate(transport=transport, url=url, command=command)
        enforce_zero_cost_transport(
            transport=connection.transport,
            external_integrations=self.settings.external_integrations,
        )
        if auth_secret_reference is not None:
            FakeSecretResolver().resolve_reference(auth_secret_reference)

        request_payload = {
            "workspace_id": workspace_id,
            "name": name,
            "transport": transport,
            "url": url,
            "command": command,
            "auth_secret_reference": auth_secret_reference,
        }
        # Scope is stable per (actor, workspace) regardless of payload, so reusing a key
        # with a different name/transport/command correctly hits the request_hash check
        # below and returns 409 instead of silently creating a second server.
        scope = f"user:{actor.user_id}:mcp-add-server:{workspace_id}"

        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            existing_response = _idempotent_write(
                conn,
                scope=scope,
                idempotency_key=idempotency_key,
                request_payload=request_payload,
            )
            if existing_response is not None:
                return existing_response

            connection_config = {
                "transport": connection.transport.value,
                "command": list(connection.command) if connection.command else None,
                "url": connection.url,
            }
            server = MCPServerRepository(conn).create(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                name=name,
                transport=connection.transport.value,
                trust_level=connection.trust_level.value,
                connection_config=connection_config,
                auth_secret_reference=auth_secret_reference,
                created_by=actor.user_id,
            )
            response = {"server": server}
            IdempotencyRepository(conn).save(
                scope=scope,
                key=idempotency_key,
                request_hash=canonical_hash(request_payload),
                response_payload=response,
                status_code=201,
            )
            return response

    def test_server(self, actor: ActorContext, server_id: str) -> dict[str, Any]:
        server = self.get_server(actor, server_id)
        self._require_admin(actor, server["workspace_id"])
        connection = connection_for_server(server)
        transport = _transport_for(connection.transport)
        try:
            result = transport.health_check(connection, timeout_ms=MCP_DISCOVERY_TIMEOUT_MS)
        except MCPAuthError as exc:
            updated = self._record_health(
                server_id=server_id,
                tenant_id=server["tenant_id"],
                actor_id=actor.user_id,
                status="auth_expired",
                healthy=False,
                error=str(exc),
            )
            return {"server": updated, "healthy": False, "error": "auth_expired"}
        except (MCPTransportError, MCPProtocolViolation) as exc:
            updated = self._record_health(
                server_id=server_id,
                tenant_id=server["tenant_id"],
                actor_id=actor.user_id,
                status="unreachable",
                healthy=False,
                error=str(exc),
            )
            return {"server": updated, "healthy": False, "error": "unreachable"}
        updated = self._record_health(
            server_id=server_id,
            tenant_id=server["tenant_id"],
            actor_id=actor.user_id,
            status="healthy",
            healthy=True,
            error=None,
        )
        return {
            "server": updated,
            "healthy": True,
            "protocol_version": result.protocol_version,
            "server_name": result.server_name,
        }

    def disable_server(
        self, actor: ActorContext, server_id: str, *, expected_version: int, idempotency_key: str
    ) -> dict[str, Any]:
        server = self.get_server(actor, server_id)
        self._require_admin(actor, server["workspace_id"])
        request_payload = {"server_id": server_id, "expected_version": expected_version}
        scope = f"user:{actor.user_id}:mcp-disable-server:{server_id}"
        with self.database.transaction(
            tenant_id=server["tenant_id"], actor_id=actor.user_id
        ) as conn:
            existing_response = _idempotent_write(
                conn,
                scope=scope,
                idempotency_key=idempotency_key,
                request_payload=request_payload,
            )
            if existing_response is not None:
                return existing_response
            updated = MCPServerRepository(conn).disable(
                server_id=server_id, expected_version=expected_version
            )
            mapping_repo = MCPToolMappingRepository(conn)
            registry = ToolRegistryRepository(conn)
            for mapping in mapping_repo.list_for_server(server_id=server_id):
                if mapping["status"] != "enabled":
                    continue
                disabled = mapping_repo.disable(
                    mapping_id=mapping["id"],
                    expected_version=mapping["version"],
                    reviewed_by=actor.user_id,
                )
                if disabled["mapped_tool_version_id"] is not None:
                    registry.retire(tool_version_id=disabled["mapped_tool_version_id"])
            response = {"server": updated}
            IdempotencyRepository(conn).save(
                scope=scope,
                key=idempotency_key,
                request_hash=canonical_hash(request_payload),
                response_payload=response,
                status_code=200,
            )
            return response

    # -- discovery -----------------------------------------------------------

    def discover_server(
        self, actor: ActorContext, server_id: str, *, idempotency_key: str
    ) -> dict[str, Any]:
        server = self.get_server(actor, server_id)
        self._require_admin(actor, server["workspace_id"])
        if not server["enabled"]:
            raise ProblemError(409, "mcp_server_disabled", "The MCP server is disabled.")

        connection = connection_for_server(server)
        transport = _transport_for(connection.transport)
        try:
            result = transport.discover(connection, timeout_ms=MCP_DISCOVERY_TIMEOUT_MS)
        except MCPAuthError as exc:
            self._record_health(
                server_id=server_id,
                tenant_id=server["tenant_id"],
                actor_id=actor.user_id,
                status="auth_expired",
                healthy=False,
                error=str(exc),
            )
            raise ProblemError(
                502, "mcp_auth_expired", "The MCP server rejected credentials."
            ) from exc
        except (MCPTransportError, MCPProtocolViolation) as exc:
            self._record_health(
                server_id=server_id,
                tenant_id=server["tenant_id"],
                actor_id=actor.user_id,
                status="unreachable",
                healthy=False,
                error=str(exc),
            )
            raise ProblemError(
                502, "mcp_server_unreachable", "The MCP server could not be discovered."
            ) from exc

        request_payload = {"server_id": server_id}
        scope = f"user:{actor.user_id}:mcp-discover:{server_id}"
        with self.database.transaction(
            tenant_id=server["tenant_id"], actor_id=actor.user_id
        ) as conn:
            existing_response = _idempotent_write(
                conn,
                scope=scope,
                idempotency_key=idempotency_key,
                request_payload=request_payload,
            )
            if existing_response is not None:
                return existing_response

            MCPServerRepository(conn).record_health(
                server_id=server_id, status="healthy", healthy=True, error=None
            )
            snapshot = MCPCapabilitySnapshotRepository(conn).create(
                tenant_id=server["tenant_id"],
                workspace_id=server["workspace_id"],
                server_id=server_id,
                protocol_version=result.protocol_version,
                capability_hash=capability_hash(result.tools),
                tools=[
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.input_schema,
                        "suspicious": tool.suspicious,
                    }
                    for tool in result.tools
                ],
                created_by=actor.user_id,
            )
            mapping_repo = MCPToolMappingRepository(conn)
            registry = ToolRegistryRepository(conn)
            seen_names: list[str] = []
            for tool in result.tools:
                seen_names.append(tool.name)
                prior = mapping_repo.get_by_server_and_name(
                    server_id=server_id, remote_tool_name=tool.name
                )
                mapping = mapping_repo.upsert_discovered(
                    tenant_id=server["tenant_id"],
                    workspace_id=server["workspace_id"],
                    server_id=server_id,
                    remote_tool_name=tool.name,
                    schema_hash=tool.schema_hash,
                    snapshot_id=snapshot["id"],
                )
                if (
                    prior is not None
                    and prior["status"] == "enabled"
                    and mapping["status"] == "drifted"
                    and prior["mapped_tool_version_id"] is not None
                ):
                    registry.retire(tool_version_id=prior["mapped_tool_version_id"])
            removed = mapping_repo.mark_missing_as_removed(
                server_id=server_id, seen_remote_tool_names=seen_names
            )
            for row in removed:
                if row["mapped_tool_version_id"] is not None:
                    registry.retire(tool_version_id=row["mapped_tool_version_id"])

            response = {
                "snapshot": snapshot,
                "mappings": mapping_repo.list_for_server(server_id=server_id),
                "removed_count": len(removed),
            }
            IdempotencyRepository(conn).save(
                scope=scope,
                key=idempotency_key,
                request_hash=canonical_hash(request_payload),
                response_payload=response,
                status_code=200,
            )
            return response

    # -- mapping review -------------------------------------------------------

    def enable_mapping(
        self,
        actor: ActorContext,
        server_id: str,
        mapping_id: str,
        *,
        forge_tool_name: str,
        risk: str,
        expected_schema_hash: str,
        expected_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        server = self.get_server(actor, server_id)
        self._require_admin(actor, server["workspace_id"])
        try:
            risk_value = ToolRisk(risk)
        except ValueError as exc:
            raise ProblemError(
                422, "mcp_risk_invalid", "Risk must be read_only or simulated_effect."
            ) from exc
        if not forge_tool_name.startswith("mcp.") or len(forge_tool_name) > FORGE_TOOL_NAME_MAX:
            raise ProblemError(
                422,
                "mcp_forge_tool_name_invalid",
                "The Forge-facing tool name must start with 'mcp.' and be bounded.",
            )

        request_payload = {
            "server_id": server_id,
            "mapping_id": mapping_id,
            "forge_tool_name": forge_tool_name,
            "risk": risk,
            "expected_schema_hash": expected_schema_hash,
            "expected_version": expected_version,
        }
        scope = f"user:{actor.user_id}:mcp-enable:{server_id}:{mapping_id}"

        with self.database.transaction(
            tenant_id=server["tenant_id"], actor_id=actor.user_id
        ) as conn:
            existing_response = _idempotent_write(
                conn,
                scope=scope,
                idempotency_key=idempotency_key,
                request_payload=request_payload,
            )
            if existing_response is not None:
                return existing_response

            mapping_repo = MCPToolMappingRepository(conn)
            mapping = mapping_repo.get_for_update(mapping_id=mapping_id)
            if mapping["mcp_server_id"] != server_id:
                raise ProblemError(
                    404, "mcp_mapping_not_found", "The MCP tool mapping was not found."
                )
            if mapping["status"] not in {"discovered", "drifted"}:
                raise ProblemError(
                    409,
                    "mcp_mapping_not_reviewable",
                    "Only a discovered or drifted mapping can be enabled.",
                )
            if mapping["version"] != expected_version:
                raise ProblemError(
                    409, "mcp_mapping_version_conflict", "MCP mapping version changed."
                )
            if mapping["schema_hash"] != expected_schema_hash:
                raise ProblemError(
                    409,
                    "mcp_mapping_schema_changed",
                    "The remote tool schema changed since it was reviewed; re-discover first.",
                )

            snapshot = None
            if mapping["latest_snapshot_id"] is not None:
                snapshot = conn.execute(
                    "select tools from mcp_capability_snapshots where id = %s",
                    (mapping["latest_snapshot_id"],),
                ).fetchone()
            input_schema: dict[str, Any] = {"type": "object", "additionalProperties": True}
            description = f"MCP tool '{mapping['remote_tool_name']}' from server {server['name']}."
            if snapshot is not None:
                for entry in snapshot["tools"]:
                    if entry["name"] == mapping["remote_tool_name"]:
                        input_schema = entry["input_schema"]
                        description = entry["description"] or description
                        break

            registry = ToolRegistryRepository(conn)
            tool_definition_id = registry.upsert_mcp_tool_definition(
                tenant_id=server["tenant_id"],
                workspace_id=server["workspace_id"],
                name=forge_tool_name,
                display_name=forge_tool_name,
                description=description[:1000],
            )
            next_version = registry.next_version_number(tool_definition_id=tool_definition_id)
            tool_version_id = registry.insert_mcp_tool_version(
                tenant_id=server["tenant_id"],
                workspace_id=server["workspace_id"],
                tool_definition_id=tool_definition_id,
                name=forge_tool_name,
                version=next_version,
                risk=risk_value.value,
                input_schema=input_schema,
                output_schema={"type": "object", "additionalProperties": True},
                timeout_ms=MCP_DISCOVERY_TIMEOUT_MS,
                retryable=risk_value is ToolRisk.READ_ONLY,
            )
            updated = mapping_repo.enable(
                mapping_id=mapping_id,
                expected_version=expected_version,
                forge_tool_name=forge_tool_name,
                risk=risk_value.value,
                tool_definition_id=tool_definition_id,
                tool_version_id=tool_version_id,
                reviewed_by=actor.user_id,
            )
            response = {
                "mapping": updated,
                "tool_name": forge_tool_name,
                "tool_version": next_version,
            }
            IdempotencyRepository(conn).save(
                scope=scope,
                key=idempotency_key,
                request_hash=canonical_hash(request_payload),
                response_payload=response,
                status_code=200,
            )
            return response

    def disable_mapping(
        self,
        actor: ActorContext,
        server_id: str,
        mapping_id: str,
        *,
        expected_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        server = self.get_server(actor, server_id)
        self._require_admin(actor, server["workspace_id"])
        request_payload = {
            "server_id": server_id,
            "mapping_id": mapping_id,
            "expected_version": expected_version,
        }
        scope = f"user:{actor.user_id}:mcp-disable-mapping:{server_id}:{mapping_id}"
        with self.database.transaction(
            tenant_id=server["tenant_id"], actor_id=actor.user_id
        ) as conn:
            existing_response = _idempotent_write(
                conn,
                scope=scope,
                idempotency_key=idempotency_key,
                request_payload=request_payload,
            )
            if existing_response is not None:
                return existing_response
            mapping_repo = MCPToolMappingRepository(conn)
            mapping = mapping_repo.get_for_update(mapping_id=mapping_id)
            if mapping["mcp_server_id"] != server_id:
                raise ProblemError(
                    404, "mcp_mapping_not_found", "The MCP tool mapping was not found."
                )
            updated = mapping_repo.disable(
                mapping_id=mapping_id,
                expected_version=expected_version,
                reviewed_by=actor.user_id,
            )
            if updated["mapped_tool_version_id"] is not None:
                ToolRegistryRepository(conn).retire(
                    tool_version_id=updated["mapped_tool_version_id"]
                )
            response = {"mapping": updated}
            IdempotencyRepository(conn).save(
                scope=scope,
                key=idempotency_key,
                request_hash=canonical_hash(request_payload),
                response_payload=response,
                status_code=200,
            )
            return response

    # -- helpers ---------------------------------------------------------------

    def _resolve_workspace(self, actor: ActorContext, workspace_id: str) -> dict[str, Any]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            scope = WorkflowRepository(conn).workspace_scope_for_actor(
                actor_id=actor.user_id, workspace_id=workspace_id
            )
        if scope is None:
            raise ProblemError(403, "workspace_forbidden", "The workspace is not accessible.")
        return dict(scope)

    def _require_admin(self, actor: ActorContext, workspace_id: str) -> None:
        decision = AuthorizationService().decide_workspace(
            actor, workspace_id, Capability.MCP_ADMIN
        )
        if not decision.allowed:
            raise ProblemError(403, "mcp_admin_forbidden", "MCP administration is not allowed.")

    def _record_health(
        self,
        *,
        server_id: str,
        tenant_id: str,
        actor_id: str,
        status: str,
        healthy: bool,
        error: str | None,
    ) -> dict[str, Any]:
        with self.database.transaction(tenant_id=tenant_id, actor_id=actor_id) as conn:
            return MCPServerRepository(conn).record_health(
                server_id=server_id, status=status, healthy=healthy, error=error
            )
