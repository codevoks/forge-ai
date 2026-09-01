from typing import Any

from forge_api.api.errors import ProblemError
from forge_api.domain.approvals import FakeSecretResolver
from forge_api.domain.mcp import MCP_INVOCATION_TIMEOUT_MS as MCP_INVOCATION_TIMEOUT_MS
from forge_api.domain.mcp import (
    MCPConnectionConfig,
    MCPTransportKind,
    MCPTrustLevel,
)
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.mcp_repositories import MCPServerRepository, MCPToolMappingRepository
from forge_api.infrastructure.mcp_transport import HttpMCPTransport, StdioMCPTransport
from forge_api.ports.mcp import (
    MCPAuthError,
    MCPClientPort,
    MCPProtocolViolation,
    MCPTimeoutAfterSendError,
    MCPTransportError,
)


class MCPOutcomeUnknownError(Exception):
    """The MCP request was sent but no response arrived before the timeout."""


def _transport_for(transport: MCPTransportKind) -> MCPClientPort:
    if transport is MCPTransportKind.STDIO:
        return StdioMCPTransport()
    return HttpMCPTransport()


def connection_for_server(server: dict[str, Any]) -> MCPConnectionConfig:
    config = server["connection_config"]
    auth_header = None
    if server["auth_secret_reference"]:
        resolved = FakeSecretResolver().resolve_reference(server["auth_secret_reference"])
        auth_header = f"Bearer {resolved['material']}"
    return MCPConnectionConfig(
        transport=MCPTransportKind(server["transport"]),
        trust_level=MCPTrustLevel(server["trust_level"]),
        command=tuple(config["command"]) if config.get("command") else None,
        url=config.get("url"),
        allow_remote=MCPTrustLevel(server["trust_level"]) is MCPTrustLevel.REMOTE,
        resolved_auth_header=auth_header,
    )


class MCPToolAdapter:
    """Implements the same adapter shape as `DeterministicToolAdapter`.

    `ToolRuntime` treats this interchangeably with the code-tool adapter: it is
    reached only after Forge has already resolved the run-scoped tool grant, exact
    schema, and risk class for an *enabled, admin-reviewed* MCP mapping. This adapter
    never bypasses that — it only performs the real remote call and returns raw
    output for the caller to validate against the pinned schema.
    """

    def __init__(self, *, database: Database) -> None:
        self.database = database

    def invoke(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        idempotency_key: str,
        worker_id: str = "mcp-tool-adapter",
    ) -> dict[str, Any]:
        _ = idempotency_key
        with self.database.transaction(worker_id=worker_id) as conn:
            mapping = MCPToolMappingRepository(conn).resolve_enabled_for_tool_name(
                forge_tool_name=tool_name
            )
            if mapping is None:
                raise ProblemError(
                    404, "mcp_tool_adapter_missing", "No enabled MCP mapping exists for this tool."
                )
            server = MCPServerRepository(conn).get_for_actor(
                actor_id="", server_id=mapping["mcp_server_id"]
            )
        if not server["enabled"] or server["status"] == "disabled":
            raise ProblemError(409, "mcp_server_disabled", "The MCP server is disabled.")

        connection = connection_for_server(server)
        transport = _transport_for(connection.transport)
        try:
            result = transport.invoke(
                connection,
                tool_name=mapping["remote_tool_name"],
                arguments=arguments,
                timeout_ms=MCP_INVOCATION_TIMEOUT_MS,
            )
        except MCPTimeoutAfterSendError as exc:
            raise MCPOutcomeUnknownError(str(exc)) from exc
        except MCPAuthError as exc:
            raise ProblemError(
                502, "mcp_auth_expired", "The MCP server rejected credentials."
            ) from exc
        except (MCPTransportError, MCPProtocolViolation) as exc:
            raise ProblemError(
                502, "mcp_invocation_failed", "The MCP tool invocation failed."
            ) from exc

        if result.is_error:
            raise ProblemError(
                502,
                "mcp_tool_reported_error",
                (result.error_message or "The MCP tool reported an error.")[:500],
            )
        return result.output
