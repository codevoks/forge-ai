"""Real MCP client transports: local stdio subprocess and remote streamable HTTP.

Both transports are deliberately one-shot: each admin operation (health check,
discovery, invocation) opens a fresh session, performs the MCP `initialize`
handshake, does its work, and tears the session down. This keeps the runtime simple
and avoids managing long-lived process/session pools for a local, low-volume admin
surface; production-capable pooling remains a documented future enhancement behind
the same `MCPClientPort`.

The HTTP transport implements the single-response ("application/json") mode of the
MCP Streamable HTTP transport. It does not implement SSE streaming or
`Mcp-Session-Id` continuity across calls — each call is its own short-lived exchange,
matching the stdio transport's one-shot design. This is a stated, documented subset,
not a claim of full transport-spec coverage.
"""

import ipaddress
import json
import queue
import socket
import subprocess
import threading
import time
from typing import Any

import httpx

from forge_api.domain.mcp import (
    MAX_DISCOVERED_TOOLS,
    MCPConnectionConfig,
    normalize_discovered_tool,
)
from forge_api.ports.mcp import (
    MCPAuthError,
    MCPDiscoveryResult,
    MCPHealthResult,
    MCPInvocationResult,
    MCPProtocolViolation,
    MCPTimeoutAfterSendError,
    MCPTransportError,
)

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "forge-ai", "version": "0.1.0"}


def _extract_tool_output(result: dict[str, Any]) -> dict[str, Any]:
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and first.get("type") == "text":
            text = str(first.get("text", ""))
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
            return parsed if isinstance(parsed, dict) else {"text": text}
    return {}


def _first_error_text(result: dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, list) and content:
        first = content[0]
        if isinstance(first, dict) and first.get("type") == "text":
            return str(first.get("text", ""))[:500]
    return "MCP tool reported an error"


class _JsonRpcStdioSession:
    def __init__(self, command: tuple[str, ...], *, timeout_ms: int) -> None:
        self._timeout_seconds = max(timeout_ms, 1) / 1000
        try:
            self._process = subprocess.Popen(  # noqa: S603
                list(command),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise MCPTransportError(f"failed to launch MCP server process: {exc}") from exc
        self._next_id = 1
        self._reader_queue: queue.Queue[str] = queue.Queue()
        self._reader_thread = threading.Thread(target=self._pump_stdout, daemon=True)
        self._reader_thread.start()

    def _pump_stdout(self) -> None:
        assert self._process.stdout is not None
        try:
            for line in self._process.stdout:
                self._reader_queue.put(line)
        except ValueError:
            return

    def _send(
        self, method: str, params: dict[str, Any], *, expect_response: bool
    ) -> dict[str, Any] | None:
        assert self._process.stdin is not None
        request_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if expect_response:
            payload["id"] = request_id
        try:
            self._process.stdin.write(json.dumps(payload) + "\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise MCPTransportError(f"MCP server pipe closed: {exc}") from exc
        if not expect_response:
            return None
        try:
            line = self._reader_queue.get(timeout=self._timeout_seconds)
        except queue.Empty as exc:
            raise MCPTimeoutAfterSendError(
                "MCP server did not respond before the timeout after the request was sent"
            ) from exc
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MCPProtocolViolation(f"MCP server returned non-JSON output: {exc}") from exc
        if not isinstance(message, dict) or message.get("id") != request_id:
            raise MCPProtocolViolation("MCP server response id did not match the request")
        if "error" in message:
            error = message["error"]
            detail = (
                error.get("message", "unknown error")
                if isinstance(error, dict)
                else "unknown error"
            )
            raise MCPTransportError(f"MCP server error: {detail}")
        result = message.get("result")
        if not isinstance(result, dict):
            raise MCPProtocolViolation("MCP server response is missing a result object")
        return result

    def initialize(self) -> dict[str, Any]:
        result = self._send(
            "initialize",
            {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO},
            expect_response=True,
        )
        assert result is not None
        self._send("notifications/initialized", {}, expect_response=False)
        return result

    def tools_list(self) -> dict[str, Any]:
        result = self._send("tools/list", {}, expect_response=True)
        assert result is not None
        return result

    def tools_call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = self._send(
            "tools/call", {"name": name, "arguments": arguments}, expect_response=True
        )
        assert result is not None
        return result

    def close(self) -> None:
        try:
            if self._process.stdin:
                self._process.stdin.close()
        except OSError:
            pass
        try:
            self._process.terminate()
            self._process.wait(timeout=2)
        except (subprocess.TimeoutExpired, OSError):
            self._process.kill()


class StdioMCPTransport:
    """Speaks real MCP JSON-RPC to a local Forge-owned subprocess."""

    def health_check(self, connection: MCPConnectionConfig, *, timeout_ms: int) -> MCPHealthResult:
        session = self._open(connection, timeout_ms=timeout_ms)
        try:
            init = session.initialize()
            server_info = init.get("serverInfo")
            name = server_info.get("name") if isinstance(server_info, dict) else None
            return MCPHealthResult(
                healthy=True,
                protocol_version=str(init.get("protocolVersion", PROTOCOL_VERSION)),
                server_name=str(name) if name else None,
                error=None,
            )
        finally:
            session.close()

    def discover(self, connection: MCPConnectionConfig, *, timeout_ms: int) -> MCPDiscoveryResult:
        session = self._open(connection, timeout_ms=timeout_ms)
        try:
            init = session.initialize()
            listing = session.tools_list()
            raw_tools = listing.get("tools", [])
            if not isinstance(raw_tools, list):
                raise MCPProtocolViolation("tools/list result.tools must be an array")
            tools = []
            for raw in raw_tools[:MAX_DISCOVERED_TOOLS]:
                if not isinstance(raw, dict):
                    continue
                normalized = normalize_discovered_tool(raw)
                if normalized is not None:
                    tools.append(normalized)
            return MCPDiscoveryResult(
                protocol_version=str(init.get("protocolVersion", PROTOCOL_VERSION)),
                tools=tools,
            )
        finally:
            session.close()

    def invoke(
        self,
        connection: MCPConnectionConfig,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_ms: int,
    ) -> MCPInvocationResult:
        session = self._open(connection, timeout_ms=timeout_ms)
        started = time.monotonic()
        try:
            session.initialize()
            result = session.tools_call(tool_name, arguments)
            latency_ms = int((time.monotonic() - started) * 1000)
            is_error = bool(result.get("isError", False))
            return MCPInvocationResult(
                output=_extract_tool_output(result),
                is_error=is_error,
                error_message=_first_error_text(result) if is_error else None,
                latency_ms=latency_ms,
            )
        finally:
            session.close()

    def _open(self, connection: MCPConnectionConfig, *, timeout_ms: int) -> _JsonRpcStdioSession:
        if connection.command is None:
            raise MCPTransportError("stdio connection is missing a command")
        return _JsonRpcStdioSession(connection.command, timeout_ms=timeout_ms)


def _default_resolve_hostname(hostname: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(hostname, None)
    except OSError as exc:
        raise MCPTransportError(f"failed to resolve MCP server host: {exc}") from exc
    return list({str(info[4][0]) for info in infos})


class HttpMCPTransport:
    """Speaks the single-response mode of MCP Streamable HTTP to a remote server.

    Every call re-resolves and re-validates the target host immediately before
    connecting (not only when the server was added) to close the DNS-rebinding
    time-of-check/time-of-use gap: a hostname that was a safe public address at
    `add_server` time could later be repointed at a private/loopback address.
    """

    def __init__(
        self,
        *,
        resolve_hostname: Any = None,
        httpx_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._resolve_hostname = resolve_hostname or _default_resolve_hostname
        self._httpx_transport = httpx_transport

    def health_check(self, connection: MCPConnectionConfig, *, timeout_ms: int) -> MCPHealthResult:
        init = self._post(
            connection, "initialize", self._initialize_params(), timeout_ms=timeout_ms
        )
        assert init is not None
        server_info = init.get("serverInfo")
        name = server_info.get("name") if isinstance(server_info, dict) else None
        return MCPHealthResult(
            healthy=True,
            protocol_version=str(init.get("protocolVersion", PROTOCOL_VERSION)),
            server_name=str(name) if name else None,
            error=None,
        )

    def discover(self, connection: MCPConnectionConfig, *, timeout_ms: int) -> MCPDiscoveryResult:
        init = self._post(
            connection, "initialize", self._initialize_params(), timeout_ms=timeout_ms
        )
        assert init is not None
        listing = self._post(connection, "tools/list", {}, timeout_ms=timeout_ms)
        assert listing is not None
        raw_tools = listing.get("tools", [])
        if not isinstance(raw_tools, list):
            raise MCPProtocolViolation("tools/list result.tools must be an array")
        tools = []
        for raw in raw_tools[:MAX_DISCOVERED_TOOLS]:
            if not isinstance(raw, dict):
                continue
            normalized = normalize_discovered_tool(raw)
            if normalized is not None:
                tools.append(normalized)
        return MCPDiscoveryResult(
            protocol_version=str(init.get("protocolVersion", PROTOCOL_VERSION)),
            tools=tools,
        )

    def invoke(
        self,
        connection: MCPConnectionConfig,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        timeout_ms: int,
    ) -> MCPInvocationResult:
        started = time.monotonic()
        self._post(connection, "initialize", self._initialize_params(), timeout_ms=timeout_ms)
        result = self._post(
            connection,
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            timeout_ms=timeout_ms,
        )
        assert result is not None
        latency_ms = int((time.monotonic() - started) * 1000)
        is_error = bool(result.get("isError", False))
        return MCPInvocationResult(
            output=_extract_tool_output(result),
            is_error=is_error,
            error_message=_first_error_text(result) if is_error else None,
            latency_ms=latency_ms,
        )

    def _initialize_params(self) -> dict[str, Any]:
        return {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": CLIENT_INFO}

    def _assert_safe_host(self, hostname: str | None) -> None:
        if not hostname:
            raise MCPTransportError("MCP server URL has no host")
        for address in self._resolve_hostname(hostname):
            ip = ipaddress.ip_address(address)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                raise MCPTransportError(
                    f"resolved address {address} for {hostname} is not a routable remote address"
                )

    def _post(
        self,
        connection: MCPConnectionConfig,
        method: str,
        params: dict[str, Any],
        *,
        timeout_ms: int,
    ) -> dict[str, Any] | None:
        if connection.url is None:
            raise MCPTransportError("http connection is missing a URL")
        self._assert_safe_host(httpx.URL(connection.url).host)
        request_id = 1
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if connection.resolved_auth_header:
            headers["Authorization"] = connection.resolved_auth_header
        try:
            with httpx.Client(
                timeout=max(timeout_ms, 1) / 1000,
                follow_redirects=False,
                transport=self._httpx_transport,
            ) as client:
                response = client.post(connection.url, json=payload, headers=headers)
        except httpx.ReadTimeout as exc:
            raise MCPTimeoutAfterSendError(
                f"MCP server did not respond before the timeout after the request was sent: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise MCPTransportError(f"MCP server timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise MCPTransportError(f"MCP server request failed: {exc}") from exc
        if response.is_redirect:
            raise MCPTransportError("MCP server attempted a redirect, which is not followed")
        if response.status_code in (401, 403):
            raise MCPAuthError(f"MCP server rejected credentials (status {response.status_code})")
        if response.status_code >= 400:
            raise MCPTransportError(f"MCP server returned status {response.status_code}")
        try:
            message = response.json()
        except ValueError as exc:
            raise MCPProtocolViolation(f"MCP server returned a non-JSON body: {exc}") from exc
        if not isinstance(message, dict) or message.get("id") != request_id:
            raise MCPProtocolViolation("MCP server response id did not match the request")
        if "error" in message:
            error = message["error"]
            detail = (
                error.get("message", "unknown error")
                if isinstance(error, dict)
                else "unknown error"
            )
            raise MCPTransportError(f"MCP server error: {detail}")
        result = message.get("result")
        if not isinstance(result, dict):
            raise MCPProtocolViolation("MCP server response is missing a result object")
        return result
