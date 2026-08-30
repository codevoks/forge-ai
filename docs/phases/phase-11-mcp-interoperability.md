# Phase 11 — MCP interoperability

## Scope

Implement an MCP client adapter for controlled local/remote servers, capability discovery, schema normalization, invocation/error mapping, auth and trust metadata; build one meaningful Forge-owned MCP server/tool as an owner exercise and integration fixture. All MCP tools pass through existing registry/policy/approval/evidence controls.

## Concepts being learned

MCP client/server roles, capabilities, discovery, transport, schemas, invocation/errors, local vs remote trust, authentication, confused deputy, capability drift, prompt-injection exposure.

## Architecture changes

MCP connections populate a quarantined discovered catalog. An administrator explicitly enables/pins mapped tool versions before planners see them. `MCPToolAdapter` implements Forge `Tool`; transport/session details never enter domain/runtime.

## Components/modules

MCP connection manager; transport/auth adapter; discovery importer/diff reviewer; schema compatibility mapper; invocation/error mapper; server health/circuit boundary; trust/risk metadata; Forge-owned example MCP server and contract tests.

## Data model changes

`mcp_servers`, discovered capability snapshots, enabled mappings/tool-version links, auth secret references, discovery diffs/last health; server/tool trust level and destination policy; invocation retains remote provenance.

## APIs and important interfaces

Admin add/test/discover/review/enable/disable server/tool; normal run tool APIs unchanged. `MCPClientPort.discover/invoke`, `MCPConnectionPolicy`, `CapabilityMapper`, `MCPToolAdapter`; server exposes at least one strict meaningful read-only tool.

## Security requirements

Explicit admin trust and allowlist; TLS/auth; SSRF/egress restrictions; no automatic enable on discovery/change; schema/risk review; least-privilege credentials per server/workspace; output untrusted; time/size/rate limits; remote errors sanitized; local server process privileges constrained.

## Failure scenarios

Server offline/slow; auth expiry; protocol/schema mismatch; tool removed/changed; malicious name/description/output; DNS rebinding/redirect; connection crosses tenant; partial discovery; duplicate invocation; server claims success ambiguously.

## Testing strategy

Protocol contract tests against fixture server; discovery drift and quarantine; auth/tenant/SSRF negatives; malicious metadata/output; timeout/retry/idempotency mapping; server disconnect/reconnect; approval for mapped high-risk tool; local vs remote trust policies.

## Acceptance criteria

Forge discovers but never auto-enables capabilities; enabled MCP tool behaves through identical policy/schema/approval/audit envelope; drift is visible and pinned runs stay safe; one meaningful server/tool is owner-built and explainable; malicious content cannot change privileges.

## Learning objectives

Build and explain an MCP server/client path, map protocol concepts to Forge boundaries, and threat-model remote/local interoperability.

## Coding exercises (private)

1. Minimal meaningful MCP server/tool.
2. Discovery snapshot/diff mapper.
3. Schema compatibility validator.
4. Malicious MCP description/output test.
5. Auth expiry/reconnect integration.

## System-design knowledge expected

Explain what MCP standardizes and does not, discovery vs authorization, transport/auth choices, remote/local trust, capability drift, invocation idempotency, and indirect-injection risk.

## Zero-cost development and demo path

Build and run the Forge-owned MCP server locally and use free/local deterministic tools for discovery, pinning, invocation, drift, and malicious-content scenarios. The real MCP client, catalog quarantine, schema normalization, policy, approval, audit, and evidence paths remain active. Paid remote servers and third-party APIs are optional integrations requiring explicit configuration; the default demo has no remote dependency.

## Explicitly deferred

Public MCP marketplace, arbitrary server installation, untrusted local processes, automatic capability approval, broad protocol feature coverage, MCP as authorization system.
