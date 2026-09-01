# Scale, observability, and cost

## Workload assumptions

These are design inputs, not measured claims.

| Dimension | Baseline design load | 100x thought experiment |
|---|---:|---:|
| Tenants / active workspaces | 100 / 500 | 10,000 / 50,000 |
| Runs created per day | 10,000 | 1,000,000 |
| Peak run submissions | 10/s | 1,000/s |
| Tasks per run (p95 / hard initial cap) | 40 / 100 | same bounded shape |
| Concurrent task attempts | 200 | 20,000 |
| Tool/model calls per run (p95) | 25 | same budgeted shape |
| Event records per task (design avg) | 10 | partition/archive required |
| Objective/evidence payload | 64 KiB inline; larger in object storage later | enforced limit |

Before production promises, Phase 13 replaces assumptions with load-test distributions and capacity math.

## What fails first at 100x

- PostgreSQL connections, hot run/tenant indexes, outbox scans, event-table growth, and lock contention.
- Redis consumer lag, pending-entry recovery, oversized payloads, and unfair tenant/provider saturation.
- Model/tool provider quotas and tail latency, often before local CPU.
- Unbounded worker concurrency causing memory/socket/database exhaustion.
- Telemetry cardinality/storage cost and UI queries over raw events.
- Cost/budget reservation races and a noisy tenant monopolizing work.

## Scaling path

1. Bound everything and measure queue age, service time, database waits, provider latency, payload sizes, and per-tenant usage.
2. Scale stateless API and workload-specific workers horizontally; keep queue messages small.
3. Tune pools/indexes, batch outbox publication, archive/partition execution events, and move large encrypted evidence to object storage.
4. Apply tenant-aware admission, fair queues, provider bulkheads, and autoscaling on oldest age/service demand.
5. Add read replicas only for explicitly stale queries; never for authorization/scheduling.
6. Partition by tenant/time or extract a workload only after traces and query plans identify the bottleneck.
7. Consider Temporal when workflow-history/operations complexity, not raw request volume alone, justifies it.

## Observability contract

One W3C trace context and Forge `correlation_id` follows API -> outbox -> queue -> worker -> model/tool/MCP. Because asynchronous work breaks parent lifetimes, spans use links as appropriate. Every log is structured and includes safe IDs: service, environment, tenant pseudonymous ID, workspace/run/task/attempt, trace/span, event type, duration, outcome, retry class. Prompts, tool bodies, credentials, tokens, and arbitrary user text are excluded by default.

Required metrics:

- API rate/error/duration and database pool/query/lock health;
- outbox unpublished age, queue depth and oldest age, claim/lease/recovery counts;
- task throughput/duration/retry/dead-letter/outcome-unknown/cancellation lag;
- model/tool/MCP latency, normalized errors, tokens, estimated/settled cost;
- approvals pending/age/expiry/rejection and policy denials;
- per-tenant budget/rate/concurrency usage and fairness;
- evaluation pass rates by suite/model/prompt/tool version (never invented);
- telemetry drops/redactions and security anomaly counters.

OpenTelemetry is the vendor-neutral instrumentation layer. LangSmith and Langfuse are optional adapters for model/agent traces, evaluation datasets, and experiment comparison, with redaction and tenant access controls. Business execution must not fail when any exporter is unavailable. LangSmith is introduced as an opt-in evaluation/trace integration: default local tests and demos use local reports and an OpenTelemetry-compatible sink, while LangSmith account-backed or self-hosted execution requires explicit approval and separate evidence.

## SLO and alert design

Initial alerts cover API availability/latency, database saturation, outbox oldest age, queue oldest age, terminal failure spike, `OUTCOME_UNKNOWN`, budget enforcement errors, approval bypass invariant violation, cross-tenant denial anomaly, and telemetry pipeline failure. Alerts state user impact and a runbook action. Provider-specific SLOs are separated from Forge-owned SLOs.

## Cost model

For each run store budget limits and normalized usage: model input/output/cached tokens, provider/model/rate snapshot, tool/API charges where known, wall/worker time, storage bytes, and attempt counts. Estimates are labeled estimates; invoices or provider usage are reconciled later.

Budgets exist at tenant, workspace, run, and operation levels. Reserve before a model/tool call using a conservative upper bound, atomically reject over-budget work, then settle actual usage. Enforce maximum iterations/calls/tokens/currency/time even when price data is missing. Rate-table updates are versioned; historical costs do not silently change.

The default development and demo rate card assigns zero monetary charge to deterministic fake providers while still recording tokens, calls, attempts, and synthetic latency so the budget machinery is exercised. A live provider rate card is inactive unless an operator deliberately selects an opt-in profile. Cost telemetry must never be presented as an invoice or production estimate unless backed by the named provider and measured run.

## Zero-cost operating profile

The mandatory portfolio profile uses local PostgreSQL, local Redis, local API/web/workers, deterministic model and third-party adapters, local MCP servers, local evaluation reports, and a local OpenTelemetry-compatible sink. It requires no domain, cloud account, LangSmith account, billing credentials, paid observability account, or large model download. Optional self-hosted components must be documented with resource bounds and may not become prerequisites for core demonstrations.

Default tests, CI, evaluations, and `pnpm demo` must fail closed if a live-provider or cloud-provisioning path is requested without an explicit opt-in flag. Infrastructure-as-code validation and planning may run locally; apply/provision/destroy commands are outside the default demo and require explicit user approval. See [Zero-cost development and demo](zero-cost-demo.md).

## Resource-efficiency rules

Use small deterministic fixtures, targeted tests, sampled/redacted trace payloads, retention tiers, no required local model downloads, and only PostgreSQL/Redis as initial local services. Do not retain every raw prompt forever or retry providers blindly.
