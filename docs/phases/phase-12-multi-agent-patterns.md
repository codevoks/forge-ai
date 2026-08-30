# Phase 12 — Measured multi-agent patterns

## Scope

Implement router/supervisor vocabulary and one justified comparison: the existing single agentic workflow versus isolated parallel specialist investigators plus deterministic/single synthesizer. Measure on a frozen evaluation suite; do not adopt multi-agent by default.

## Concepts being learned

Routing, supervision, handoffs, parallelism, shared vs isolated context, message passing, aggregation, context contamination, failure propagation, coordination overhead, cost/latency multiplication, evaluation difficulty.

## Architecture changes

Represent specialist work as ordinary child tasks with scoped context/tool grants/budgets and explicit result schemas. Supervisor is orchestration policy, not a privileged model. Aggregation consumes immutable specialist outputs/provenance. Fan-out/fan-in uses existing DAG scheduler.

## Components/modules

Strategy selector; deterministic/router policy and optional model router; specialist role/config registry; scoped context builder; fan-out coordinator; handoff/message schema; synthesizer/aggregator; failure policy; comparative evaluator/report.

## Data model changes

Execution strategy/version; parent-child task/agent role links; handoff/message records or evidence references; per-specialist budgets/usage/results; aggregation provenance and partial-failure status. Avoid free-form shared mutable memory.

## APIs and important interfaces

Run selects approved strategy/config; comparison report endpoints. `ExecutionStrategy`, `Router`, `SpecialistRequest/Result`, `Handoff`, `AggregationPolicy`, `FailurePropagationPolicy`. Same model/tool/policy ports and overall budget envelope.

## Security requirements

Least tools/context per specialist; no capability inheritance beyond explicit grants; tenant isolation; provenance-preserving aggregation; untrusted inter-agent content; bounded fan-out/depth/messages; supervisor cannot approve/authorize; total budget and cancellation propagate.

## Failure scenarios

One/all specialists fail; slow straggler; contradictory results; duplicate child; context leak/contamination; synthesizer fabricates consensus; router misroutes; supervisor loop; cancellation mid-fan-out; partial evidence and budget exhaustion.

## Testing strategy

Same frozen scenarios/models/tools/budgets where comparable; deterministic coordination/failure tests; isolate vs shared-context adversarial cases; partial/timeout policies; measure task success, latency distributions, model/token/tool calls, estimated cost, invalid/permission/error rates; statistical caveats and no cherry-picking.

## Acceptance criteria

Both strategies pass security/runtime invariants; comparison is reproducible and reports all required metrics; partial failures are explicit; owner can state where multi-agent wins/loses. Default changes only with documented material benefit and ADR.

## Learning objectives

Design router/supervisor/handoff/parallel specialist systems, implement fan-out/fan-in safely, diagnose coordination failures, and reject unjustified multi-agent complexity.

## Coding exercises (private)

1. Rule-based router and typed handoff.
2. Bounded parallel executor with cancellation.
3. Partial-failure aggregation policy.
4. Context-isolation contamination test.
5. Single-vs-multi metric comparison.
6. Supervisor-loop termination test.

## System-design knowledge expected

Defend task vs agent decomposition, supervisor authority limits, shared/isolated state, fan-out backpressure, aggregation provenance, failure/cancellation propagation, evaluation fairness, and cost/latency tradeoffs.

## Zero-cost development and demo path

Drive router, specialists, supervisor, and synthesizer with deterministic fake models over the real task DAG, worker, checkpoint, permission, budget, failure-propagation, and aggregation architecture. The single-versus-multi comparison uses frozen local scenarios and records synthetic token/cost fields without spending money. Any live-model comparison is optional, explicitly enabled, capped, and excluded from the portfolio gate.

## Explicitly deferred

Agent swarms, recursive delegation, debate by default, free-form peer chat, shared mutable memory, per-agent services, default adoption without evidence.
