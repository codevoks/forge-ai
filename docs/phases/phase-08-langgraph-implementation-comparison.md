# Phase 8 — LangGraph implementation and comparison

## Scope

Implement the same bounded flagship workflow with LangGraph `StateGraph`, nodes, conditional edges, reducers, tool nodes, checkpointer, interrupts, approval, and termination. Preserve Forge domain/policy/persistence authority and compare against the custom runtime.

## Concepts being learned

Framework abstractions over state machines, reducer semantics, checkpoint/interrupt lifecycle, graph composition, adapter boundaries, framework lock-in and equivalence testing.

## Architecture changes

Add `WorkflowEngine` strategy with custom and LangGraph implementations. LangGraph state stores references/minimal resumable state, not a second tenant/security database. Forge tool executor and approval services remain mandatory nodes/boundaries; LangGraph cannot invoke provider tools directly around them.

## Components/modules

LangGraph state schema; planner/executor/tool/approval/checkpoint nodes; conditional routing; Forge checkpointer adapter; engine selector; parity scenario runner; comparison report instrumentation.

## Data model changes

Engine kind/version on runs; engine checkpoint metadata/namespace mapped to Forge run/task; no duplicate authoritative task/approval tables. Migration/retention rules for framework checkpoint serialization.

## APIs and important interfaces

Existing run APIs unchanged except inspectable engine metadata. `WorkflowEngine.start/resume/cancel`, state mapping, checkpoint adapter. Tool/policy/model ports unchanged, proving containment.

## Security requirements

Tenant namespacing for checkpoints; safe serialization; no secrets; interrupts cannot bypass approval; engine resume rechecks policy/cancellation; framework debug output redacted; dependency review/pinning.

## Failure scenarios

Crash before/after node/checkpoint; duplicate resume; reducer conflict; incompatible checkpoint after upgrade; approval interrupt race; cancellation while suspended; framework retry conflicts with Forge retry; tool node bypass attempt.

## Testing strategy

Contract tests run identical scenario suite against both engines; state/event/result parity; checkpoint crash/recovery; interrupt approval; termination/budget/security tests; migration compatibility; measure code complexity, latency, history size, debugging quality without cherry-picking.

## Acceptance criteria

LangGraph path completes the same cases with identical policy/effect invariants; owner can map every node/edge/reducer/checkpoint/interrupt to custom mechanics; comparison records measured pros/cons and an evidence-based adoption scope.

## Learning objectives

Build a minimal LangGraph from memory, explain what it abstracts and does not, debug state/reducer/checkpoint behavior, and choose framework scope without dependency mysticism.

## Coding exercises (private)

1. Minimal `StateGraph` with conditional edges.
2. Reducer conflict exercise.
3. Tool node through Forge policy envelope.
4. Checkpoint/resume crash exercise.
5. Approval interrupt/cancel test.

## System-design knowledge expected

Compare custom vs LangGraph state ownership, durability, security, observability, migrations, retries, developer velocity, and lock-in; explain why framework state cannot become shadow authority.

## Zero-cost development and demo path

Use the open-source LangGraph library locally with the same deterministic fake model, local tools, policies, datasets, and PostgreSQL-backed Forge authority as the custom runtime comparison. No hosted LangGraph service, paid tracing product, or live model is required. Measure only locally observable parity and complexity; do not claim managed-service operational behavior. Heavy optional services must not enter the default demo profile.

## Explicitly deferred

Multi-agent LangGraph; framework default switch until Phase 9 evidence; Temporal; MCP; large-scale checkpoint benchmarking beyond focused comparison.
