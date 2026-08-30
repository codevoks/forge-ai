# Phase 4 — Typed tool runtime

## Scope

Implement versioned code-registered tools, strict Pydantic v2 input/output validation, allowlists, capability/risk policy, timeouts, retry/idempotency metadata, invocation intent/result ledger, evidence provenance, and a few deterministic read-only/simulated tools. No LLM-selected calls or irreversible real-world effect.

## Concepts being learned

Tool contracts, schema boundaries, registry/versioning, authorization vs validation, side-effect taxonomy, idempotent effects, timeouts, untrusted output, dependency inversion.

## Architecture changes

Workers execute `AuthorizedInvocation` only after registry resolution, schema normalization, actor/run policy, risk, and budget prechecks. Registry metadata is immutable and pinned to runs. Tool adapters cannot access broad application services or arbitrary credentials.

## Components/modules

Tool definition/decorator or explicit registrar; registry; policy/risk classifier; input canonicalizer/action hasher; invocation orchestrator; sandboxed deterministic fixtures such as deployment-history/customer-report read tools; evidence sanitizer/provenance; fake effect provider and reconciliation seam.

## Data model changes

`tool_definitions`, `tool_versions`, `run_tool_grants`, `tool_invocations`, `evidence_items`; invocation status/idempotency/action hash/provider ID/outcome; risk and schema version; content trust/source/hash/retention fields.

## APIs and important interfaces

Authorized tool catalog/read endpoints and admin registration visibility; invocation inspection. `Tool`, `ToolDefinition`, `ToolRegistry.resolve`, `RiskPolicy.classify`, `ToolPolicy.authorize`, `ToolExecutor.invoke`, `ToolResult`, `EvidenceSanitizer`. No generic endpoint that accepts arbitrary tool names without run context.

## Security requirements

Deny unregistered/ungranted/version-mismatched calls; derive tenant/account scope server-side; strict schemas with unknown fields rejected; size/content/time limits; output trust labels; no secret logging/context; destination allowlists for any network fake; effects simulated until approvals exist.

## Failure scenarios

Hallucinated tool/version; malformed/oversized input/output; timeout; retryable vs permanent adapter error; duplicate invocation; provider success then worker crash; credential revoked; malicious tool output; tool version removed while run pinned.

## Testing strategy

Schema/property tests; permission/risk matrix; duplicate logical-invocation tests; timeout/cancellation; fake provider ambiguous outcome/reconciliation; untrusted-output injection fixtures; tenant scope; registry immutability and pinned-version behavior.

## Acceptance criteria

Only exact granted tool versions execute; invalid calls never reach adapters; invocation intent precedes execution; duplicate safe calls collapse and ambiguous effects become visible; all outputs carry provenance/trust; deterministic workflow can call fixture tools without a model.

## Learning objectives

Implement a typed Pydantic tool, permission envelope, and idempotency ledger; defend why a schema is necessary but insufficient and why tool output is untrusted.

## Coding exercises (private)

1. Typed tool with strict input/output schemas.
2. Canonical JSON/action-hash implementation.
3. Tool permission/risk decision table.
4. Timeout and normalized-error adapter.
5. Duplicate side-effect fake with reconciliation.

## System-design knowledge expected

Explain registry ownership, immutable versions, capability projection, risk vs authorization, confused deputy, provider idempotency limits, evidence provenance, and local/remote trust differences.

## Zero-cost development and demo path

Provide meaningful local deterministic read tools and a fake external-effect provider. Exercise the real versioned registry, schemas, grants, risk classification, intent ledger, action hashing, idempotency, provenance, ambiguous-outcome state, and reconciliation seam. Do not require paid third-party APIs, hosted secret managers, browser services, or notification products. Production adapters remain behind `Tool`, effect-provider, and secret-reference ports and are disabled by default.

## Explicitly deferred

Model planning/calling; human approval and real high-risk effects; remote MCP; arbitrary network/browser/shell tools; secrets manager implementation; sandboxed untrusted code.
