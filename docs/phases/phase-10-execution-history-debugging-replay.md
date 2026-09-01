# Phase 10 — Execution history, debugger, safe replay, and trace export

## Scope

Make execution history operable: event catalog/versioning, timeline and graph debugger, causation/correlation, state-diff explanations, LangGraph checkpoint/state inspection, trace links, cursor/SSE progress if justified, projection verification, trace export seams, and replay modes with simulation as default.

## Concepts being learned

Event history vs event sourcing, audit/provenance, causal tracing, projections, replay determinism limits, schema evolution, debugging asynchronous systems, observability cardinality/redaction.

## Architecture changes

Formalize event schemas and query projection; add replay service isolated from production effects; connect event IDs to OTel spans/model/tool records and the Phase 9 LangSmith export seam. Add LangGraph checkpoint correlation for engine-comparison runs. Add SSE only over cursor/resume semantics and keep polling baseline.

## Components/modules

Event catalog/upcasters; timeline/query projection; state-diff/explanation builder; LangGraph checkpoint/state inspector; replay planner/runner with recorded/fake adapters; projection verifier; OTel/LangSmith trace-link adapter; SSE gateway if measured; debugger UI; retention/archive jobs.

## Data model changes

Event schema version, causation/correlation/trace links, sanitized diff metadata; replay sessions/lineage/artifacts; projection verification results; indexes/partition readiness and retention markers.

## APIs and important interfaces

Cursor event feed, task/attempt/model/tool detail, replay preview/start/status, projection verify. `EventSerializer/Upcaster`, `ReplayPolicy`, `ReplayAdapterSet`, `ProjectionVerifier`. Effect replay requires separate explicit command and is disabled initially.

## Security requirements

Events/traces tenant-scoped and redacted; raw payload access capability-controlled; output encoded; cursor unforgeable or scope-revalidated; replay cannot reuse approvals/credentials or execute effects; LangGraph checkpoints cannot become replay authority; LangSmith/telemetry export is opt-in, redacted, and failure-isolated; exported history audited and retention-aware.

## Failure scenarios

Missing/duplicate/out-of-order export, unknown event version, stale cursor, SSE reconnect, projection mismatch, huge history, replay hits real adapter, model nondeterminism, deleted evidence, LangGraph checkpoint mismatch, telemetry backend outage, LangSmith exporter disabled/auth/rate-limit failure.

## Testing strategy

Event schema compatibility/golden tests; causal ordering and cursor pagination; SSE reconnect if present; projection fold vs current state; LangGraph checkpoint correlation tests; simulation adapter tripwire proving no effects; replay comparisons; redaction/tenant/export tests; LangSmith disabled/exporter-failure tests; history performance and retention jobs.

## Acceptance criteria

Operator can explain a run from objective to terminal state and locate failure/retry/approval cause; LangGraph runs show graph checkpoint evidence beside Forge events without transferring authority; cursor feed resumes without silent loss; projection verifier detects corruption; simulation replay cannot call real effects; nondeterministic differences are labeled; telemetry outage does not block execution.

## Learning objectives

Debug an asynchronous run from evidence, implement a replay fragment, explain projections/upcasting/causation, and distinguish execution audit from provider telemetry.

## Coding exercises (private)

1. Event fold/projection verifier.
2. Causation/correlation timeline builder.
3. Cursor reconnect/dedup client.
4. Event upcaster.
5. Safe replay adapter tripwire.

## System-design knowledge expected

Defend event/state dual model, ordering guarantees, schema evolution, replay modes, trace propagation, telemetry failure isolation, retention/cardinality, and why model replay is comparative rather than deterministic.

## Zero-cost development and demo path

Use Forge's local event history and projection verification as the authoritative debugger, with local OpenTelemetry collection and a free local Jaeger-compatible viewer/sink only where visual trace inspection adds value. Safe replay must substitute deterministic model/tool/effect adapters and prove that real side effects cannot be reached. LangSmith/Langfuse Cloud or another paid backend is not required; vendor adapters remain optional and telemetry failure cannot affect execution.

## Explicitly deferred

Forensic/compliance immutability services, arbitrary effect replay, warehouse analytics, long-term cold archive implementation, final cloud observability topology.
