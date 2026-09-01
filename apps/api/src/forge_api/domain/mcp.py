"""MCP interoperability domain rules: connection shape, discovery quarantine, and drift.

An MCP server is only ever a source of *proposed* capabilities. Nothing here grants
execution authority: discovery produces a quarantined snapshot, an administrator must
explicitly review and enable a mapping, and Forge's existing tool registry/policy/
approval/evidence machinery (see `forge_api.domain.tools`) remains the sole authority
for what actually executes. Remote tool descriptions and outputs are always untrusted
content, never instructions.
"""

import hashlib
import json
import re
import sys
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from forge_api.api.errors import ProblemError
from forge_api.domain import json_schema
from forge_api.domain.approvals import NetworkPolicy

MAX_MCP_TOOL_NAME = 80
MAX_MCP_DESCRIPTION = 1000
MAX_DISCOVERED_TOOLS = 50
MCP_INVOCATION_TIMEOUT_MS = 5000
MCP_DISCOVERY_TIMEOUT_MS = 5000

# Stdio servers may only launch a Forge-owned module with the current interpreter.
# This is a deliberate, narrow allowlist: MCP server "installation" is not supported;
# only a Forge-authored, reviewable fixture/integration server may run as a local
# subprocess. See docs/phases/phase-11-mcp-interoperability.md "Explicitly deferred".
ALLOWED_STDIO_MODULES = {"forge_api.scripts.mcp_fixture_server"}

_TOOL_NAME_RE = re.compile(rf"^[a-zA-Z0-9_.\-]{{1,{MAX_MCP_TOOL_NAME}}}$")
_SUSPICIOUS_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "system prompt",
    "you are now",
    "disregard your instructions",
)


class MCPTransportKind(StrEnum):
    STDIO = "stdio"
    HTTP = "http"


class MCPTrustLevel(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"


class MCPServerStatus(StrEnum):
    DRAFT = "draft"
    HEALTHY = "healthy"
    UNREACHABLE = "unreachable"
    AUTH_EXPIRED = "auth_expired"
    DISABLED = "disabled"


class MCPMappingStatus(StrEnum):
    DISCOVERED = "discovered"
    ENABLED = "enabled"
    DISABLED = "disabled"
    DRIFTED = "drifted"
    REMOVED = "removed"


@dataclass(frozen=True)
class MCPToolMetadata:
    name: str
    description: str
    input_schema: dict[str, Any]
    suspicious: bool

    @property
    def schema_hash(self) -> str:
        payload = {"name": self.name, "input_schema": self.input_schema}
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def capability_hash(tools: list[MCPToolMetadata]) -> str:
    payload = [{"name": t.name, "input_schema": t.input_schema} for t in tools]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def flag_suspicious_text(*fragments: str) -> bool:
    """Advisory-only heuristic for the discovery review surface.

    This never becomes a security boundary by itself (see
    docs/architecture/security-threat-model.md "Prompt-injection controls" #6):
    flagged or not, remote tool descriptions/output remain untrusted data that
    cannot change policy, permissions, or execution.
    """
    lowered = " ".join(fragments).lower()
    return any(marker in lowered for marker in _SUSPICIOUS_MARKERS)


def normalize_discovered_tool(raw: dict[str, Any]) -> MCPToolMetadata | None:
    """Bound and validate one raw MCP `tools/list` entry. Returns None if it must be rejected."""
    name = raw.get("name")
    description = raw.get("description") or ""
    input_schema = raw.get("inputSchema") or raw.get("input_schema") or {"type": "object"}
    if not isinstance(name, str) or not _TOOL_NAME_RE.match(name):
        return None
    if not isinstance(description, str) or len(description) > MAX_MCP_DESCRIPTION:
        return None
    if json_schema.validate_schema_shape(input_schema):
        return None
    return MCPToolMetadata(
        name=name,
        description=description[:MAX_MCP_DESCRIPTION],
        input_schema=input_schema,
        suspicious=flag_suspicious_text(name, description),
    )


@dataclass(frozen=True)
class MCPConnectionConfig:
    transport: MCPTransportKind
    trust_level: MCPTrustLevel
    command: tuple[str, ...] | None
    url: str | None
    allow_remote: bool
    resolved_auth_header: str | None = None

    def with_auth_header(self, header: str | None) -> "MCPConnectionConfig":
        return replace(self, resolved_auth_header=header)


class MCPConnectionPolicy:
    """Validates a proposed server connection before it is ever persisted or dialed."""

    def validate(
        self, *, transport: str, url: str | None, command: list[str] | None
    ) -> MCPConnectionConfig:
        try:
            kind = MCPTransportKind(transport)
        except ValueError as exc:
            raise ProblemError(422, "mcp_transport_invalid", "Unsupported MCP transport.") from exc

        if kind is MCPTransportKind.STDIO:
            return self._validate_stdio(command)
        return self._validate_http(url)

    def _validate_stdio(self, command: list[str] | None) -> MCPConnectionConfig:
        if not command or len(command) != 3:
            raise ProblemError(
                422,
                "mcp_stdio_command_invalid",
                "Stdio servers must launch an allowlisted Forge-owned module.",
            )
        interpreter, flag, module = command
        if interpreter != sys.executable or flag != "-m" or module not in ALLOWED_STDIO_MODULES:
            raise ProblemError(
                422,
                "mcp_stdio_command_not_allowlisted",
                "Only an allowlisted Forge-owned MCP server module may be launched locally.",
            )
        return MCPConnectionConfig(
            transport=MCPTransportKind.STDIO,
            trust_level=MCPTrustLevel.LOCAL,
            command=tuple(command),
            url=None,
            allow_remote=False,
        )

    def _validate_http(self, url: str | None) -> MCPConnectionConfig:
        if not url:
            raise ProblemError(422, "mcp_url_required", "Remote MCP servers require a URL.")
        validated = NetworkPolicy().validate_url(url)
        return MCPConnectionConfig(
            transport=MCPTransportKind.HTTP,
            trust_level=MCPTrustLevel.REMOTE,
            command=None,
            url=validated,
            allow_remote=True,
        )


def enforce_zero_cost_transport(*, transport: MCPTransportKind, external_integrations: str) -> None:
    """Remote MCP servers are an external integration and stay off the default zero-cost path."""
    if transport is MCPTransportKind.HTTP and external_integrations != "enabled":
        raise ProblemError(
            403,
            "mcp_remote_transport_disabled",
            "Remote MCP servers require FORGE_EXTERNAL_INTEGRATIONS=enabled.",
        )
