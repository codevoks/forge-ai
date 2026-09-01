"""The narrow interface Forge depends on for MCP client behavior.

Transport (stdio subprocess, HTTP) is an infrastructure detail behind this port; the
application layer only ever sees `MCPClientPort` and its result/error types. This
keeps MCP protocol/transport specifics out of domain and application code, matching
the same narrow-port pattern used for `ModelProvider` and `QueuePort`.
"""

from dataclasses import dataclass
from typing import Any, Protocol

from forge_api.domain.mcp import MCPConnectionConfig, MCPToolMetadata


class MCPTransportError(Exception):
    """The server could not be reached, timed out, or the process/connection failed."""


class MCPTimeoutAfterSendError(MCPTransportError):
    """A request was already sent to the server when the timeout fired.

    Unlike a connect-time failure, Forge cannot know whether the remote tool ran.
    Callers must treat this the same way as any other ambiguous external effect
    (see `forge_api.application.tool_runtime.OutcomeUnknownToolError`): record
    `outcome_unknown` and require reconciliation rather than silently retrying.
    """


class MCPAuthError(Exception):
    """The server rejected the configured credential."""


class MCPProtocolViolation(Exception):
    """The server returned a response that does not conform to JSON-RPC/MCP shape."""


@dataclass(frozen=True)
class MCPHealthResult:
    healthy: bool
    protocol_version: str | None
    server_name: str | None
    error: str | None


@dataclass(frozen=True)
class MCPDiscoveryResult:
    protocol_version: str
    tools: list[MCPToolMetadata]


@dataclass(frozen=True)
class MCPInvocationResult:
    output: dict[str, Any]
    is_error: bool
    error_message: str | None
    latency_ms: int


class MCPClientPort(Protocol):
    def health_check(
        self, connection: MCPConnectionConfig, *, timeout_ms: int
    ) -> MCPHealthResult: ...

    def discover(
        self, connection: MCPConnectionConfig, *, timeout_ms: int
    ) -> MCPDiscoveryResult: ...

    def invoke(
        self,
        connection: MCPConnectionConfig,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_ms: int,
    ) -> MCPInvocationResult: ...
