import json
import sys

import httpx
import pytest

from forge_api.domain.mcp import MCPConnectionConfig, MCPTransportKind, MCPTrustLevel
from forge_api.infrastructure.mcp_transport import HttpMCPTransport, StdioMCPTransport
from forge_api.ports.mcp import (
    MCPAuthError,
    MCPProtocolViolation,
    MCPTimeoutAfterSendError,
    MCPTransportError,
)

STDIO_COMMAND = (sys.executable, "-m", "forge_api.scripts.mcp_fixture_server")


def stdio_connection() -> MCPConnectionConfig:
    return MCPConnectionConfig(
        transport=MCPTransportKind.STDIO,
        trust_level=MCPTrustLevel.LOCAL,
        command=STDIO_COMMAND,
        url=None,
        allow_remote=False,
    )


# -- real stdio protocol contract tests (genuine subprocess, no mocks) --------------


def test_stdio_health_check_talks_real_protocol() -> None:
    result = StdioMCPTransport().health_check(stdio_connection(), timeout_ms=5000)
    assert result.healthy is True
    assert result.server_name == "forge-release-notes"


def test_stdio_discover_returns_real_tool_catalog() -> None:
    result = StdioMCPTransport().discover(stdio_connection(), timeout_ms=5000)
    names = {tool.name for tool in result.tools}
    assert names == {"search_release_notes", "lookup_worker_health"}
    for tool in result.tools:
        assert tool.suspicious is False


def test_stdio_invoke_returns_structured_output() -> None:
    result = StdioMCPTransport().invoke(
        stdio_connection(),
        tool_name="lookup_worker_health",
        arguments={"service": "worker"},
        timeout_ms=5000,
    )
    assert result.is_error is False
    assert result.output["service"] == "worker"
    assert result.output["status"] == "healthy"


def test_stdio_invoke_unknown_tool_raises_transport_error() -> None:
    with pytest.raises(MCPTransportError):
        StdioMCPTransport().invoke(
            stdio_connection(), tool_name="not_a_real_tool", arguments={}, timeout_ms=5000
        )


def test_stdio_invoke_invalid_arguments_reports_tool_error() -> None:
    result = StdioMCPTransport().invoke(
        stdio_connection(),
        tool_name="lookup_worker_health",
        arguments={"service": "not-a-real-service"},
        timeout_ms=5000,
    )
    assert result.is_error is True
    assert result.error_message


def test_stdio_launch_failure_raises_transport_error() -> None:
    bad_connection = MCPConnectionConfig(
        transport=MCPTransportKind.STDIO,
        trust_level=MCPTrustLevel.LOCAL,
        command=("/nonexistent/forge-mcp-binary",),
        url=None,
        allow_remote=False,
    )
    with pytest.raises(MCPTransportError):
        StdioMCPTransport().health_check(bad_connection, timeout_ms=1000)


def test_stdio_timeout_after_send_is_distinguishable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FORGE_MCP_FIXTURE_VARIANT", "hang")
    hang_connection = MCPConnectionConfig(
        transport=MCPTransportKind.STDIO,
        trust_level=MCPTrustLevel.LOCAL,
        command=STDIO_COMMAND,
        url=None,
        allow_remote=False,
    )
    with pytest.raises(MCPTimeoutAfterSendError):
        StdioMCPTransport().invoke(
            hang_connection,
            tool_name="search_release_notes",
            arguments={"query": "worker"},
            timeout_ms=500,
        )


# -- HTTP transport unit tests (in-memory httpx.MockTransport, zero network) --------


def http_connection(url: str = "https://example.com/mcp") -> MCPConnectionConfig:
    return MCPConnectionConfig(
        transport=MCPTransportKind.HTTP,
        trust_level=MCPTrustLevel.REMOTE,
        command=None,
        url=url,
        allow_remote=True,
    )


def _json_rpc_ok_handler(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    method = payload["method"]
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "serverInfo": {"name": "fake-remote"}}
    elif method == "tools/list":
        result = {
            "tools": [
                {"name": "remote_tool", "description": "x", "inputSchema": {"type": "object"}}
            ]
        }
    elif method == "tools/call":
        result = {"isError": False, "structuredContent": {"ok": True}}
    else:
        result = {}
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})


def test_http_transport_discovers_over_mock_transport() -> None:
    transport = HttpMCPTransport(
        resolve_hostname=lambda host: ["93.184.216.34"],
        httpx_transport=httpx.MockTransport(_json_rpc_ok_handler),
    )
    result = transport.discover(http_connection(), timeout_ms=2000)
    assert [t.name for t in result.tools] == ["remote_tool"]


def test_http_transport_invokes_over_mock_transport() -> None:
    transport = HttpMCPTransport(
        resolve_hostname=lambda host: ["93.184.216.34"],
        httpx_transport=httpx.MockTransport(_json_rpc_ok_handler),
    )
    result = transport.invoke(
        http_connection(), tool_name="remote_tool", arguments={}, timeout_ms=2000
    )
    assert result.output == {"ok": True}


def test_http_transport_maps_401_to_auth_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    transport = HttpMCPTransport(
        resolve_hostname=lambda host: ["93.184.216.34"],
        httpx_transport=httpx.MockTransport(handler),
    )
    with pytest.raises(MCPAuthError):
        transport.health_check(http_connection(), timeout_ms=2000)


def test_http_transport_rejects_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://attacker.example/"})

    transport = HttpMCPTransport(
        resolve_hostname=lambda host: ["93.184.216.34"],
        httpx_transport=httpx.MockTransport(handler),
    )
    with pytest.raises(MCPTransportError):
        transport.health_check(http_connection(), timeout_ms=2000)


def test_http_transport_rejects_non_json_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    transport = HttpMCPTransport(
        resolve_hostname=lambda host: ["93.184.216.34"],
        httpx_transport=httpx.MockTransport(handler),
    )
    with pytest.raises(MCPProtocolViolation):
        transport.health_check(http_connection(), timeout_ms=2000)


def test_http_transport_rejects_dns_rebound_private_address() -> None:
    """Even a URL that passed NetworkPolicy at add-server time is re-checked per call."""
    transport = HttpMCPTransport(
        resolve_hostname=lambda host: ["127.0.0.1"],
        httpx_transport=httpx.MockTransport(_json_rpc_ok_handler),
    )
    with pytest.raises(MCPTransportError):
        transport.health_check(http_connection(), timeout_ms=2000)


def test_http_transport_rejects_cloud_metadata_rebound_address() -> None:
    transport = HttpMCPTransport(
        resolve_hostname=lambda host: ["169.254.169.254"],
        httpx_transport=httpx.MockTransport(_json_rpc_ok_handler),
    )
    with pytest.raises(MCPTransportError):
        transport.health_check(http_connection(), timeout_ms=2000)
