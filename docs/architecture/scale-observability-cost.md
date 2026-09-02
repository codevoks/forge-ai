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

## Phase 13 measured local evidence

`pnpm capacity-report` (`apps/api/src/forge_api/scripts/capacity_report.py`) runs a real, reproducible load/soak drill on this development machine: 60 runs of the deterministic 4-step "Incident Response Demo" workflow, submitted as fast as `RunService.create` allows, drained by 4 worker threads, against one local PostgreSQL instance with **no connection pool** (`Database.transaction` opens a fresh `psycopg` connection per call today — see D-002/D-004). One representative run:

| Metric | Measured value |
|---|---:|
| Run creation throughput | 8.4 runs/sec |
| End-to-end throughput (create -> succeeded) | 5.0 runs/sec |
| Estimated task throughput | 20.2 tasks/sec |
| Run latency p50 / p95 / p99 | 5.3s / 7.1s / 7.2s |

This is a single-machine, single-process measurement — explicitly not a production capacity claim. The naive 100x linear extrapolation the script prints (~500 runs/sec) is labeled unvalidated in its own output: real capacity at that scale depends on connection pooling (not yet implemented), Redis consumer-group fanout, and horizontal worker scaling, none of which this drill exercises. Its purpose is to replace a design-input guess with one measured, reproducible local data point, and it is the evidence cited in the Q-005 Temporal ADR (`decisions.md`) for rejecting adoption: nothing in this profile is bottlenecked by workflow-history/event-sourcing mechanics, which is the specific problem Temporal solves.

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

One W3C trace context and Forge `correlation_id` follows API -> outbox -> queue -> worker. Phase 13 implements this: `RunService.create` opens a root `run.create` OTel span and threads its W3C `traceparent` through `RunRepository.create_run` into the outbox message payload for the run's initial ready tasks; `WorkerConsumer.consume_once` extracts that context, continues it in a `task.execute` span, and records a `task.trace_correlated` execution event whose `correlation_id` is the real OTel trace id (reformatted as a UUID) rather than a fresh random id per event. Tasks that become ready later via the existing completion path (not the run-creation path) get their own fresh per-attempt trace rather than continuing the root — a deliberately bounded first rollout, not full DAG-wide propagation; every attempt is still a real, correlatable OTel span, and this only affects which spans share a `trace_id`, not whether tracing exists. Every log is structured and includes safe IDs: service, environment, tenant pseudonymous ID, workspace/run/task/attempt, trace/span, event type, duration, outcome, retry class. Prompts, tool bodies, credentials, tokens, and arbitrary user text are excluded by default; span attributes are sanitized through the same `sanitize_payload` redaction used for events (`infrastructure/telemetry.py`).

Required metrics:

- API rate/error/duration and database pool/query/lock health;
- outbox unpublished age, queue depth and oldest age, claim/lease/recovery counts;
- task throughput/duration/retry/dead-letter/outcome-unknown/cancellation lag;
- model/tool/MCP latency, normalized errors, tokens, estimated/settled cost;
- approvals pending/age/expiry/rejection and policy denials;
- per-tenant budget/rate/concurrency usage and fairness;
- evaluation pass rates by suite/model/prompt/tool version (never invented);
- telemetry drops/redactions and security anomaly counters.

OpenTelemetry is the vendor-neutral instrumentation layer (`ports/telemetry.py::TelemetryPort`, `infrastructure/telemetry.py::ForgeTelemetry`). The zero-cost default attaches a local JSONL span exporter (`local/telemetry/spans.jsonl`, gitignored); an OTLP exporter — usable by any OTLP-compatible collector, including a self-hosted Langfuse or local Jaeger — attaches only when `FORGE_TELEMETRY_EXPORT_MODE=enabled` *and* `FORGE_EXTERNAL_INTEGRATIONS=enabled` *and* an endpoint is configured, so no network call is ever attempted by default; `SimpleSpanProcessor` already isolates exporter failures from the wrapped business operation. The Phase 10 debugger trace-export endpoint (`POST /v1/runs/{run_id}/debugger/trace-exports`) now surfaces real per-event `trace_id`/`correlation_id` pulled from `execution_events.trace_context`, and accepts `exporter: "local" | "langsmith" | "langfuse"` — LangSmith and Langfuse remain optional, non-authoritative adapters over that same local artifact contract, blocked by default and requiring the same explicit `enabled` opt-in. LangSmith's separate evaluation-export integration (Phase 9) follows the identical local/disabled/enabled pattern.

## SLO and alert design

Initial alerts cover API availability/latency, database saturation, outbox oldest age, queue oldest age, terminal failure spike, `OUTCOME_UNKNOWN`, budget enforcement errors, approval bypass invariant violation, cross-tenant denial anomaly, and telemetry pipeline failure. Alerts state user impact and a runbook action. Provider-specific SLOs are separated from Forge-owned SLOs.

## Cost model

For each run store budget limits and normalized usage: model input/output/cached tokens, provider/model/rate snapshot, tool/API charges where known, wall/worker time, storage bytes, and attempt counts. Estimates are labeled estimates; invoices or provider usage are reconciled later.

Budgets exist at tenant, workspace, run, and operation levels. Reserve before a model/tool call using a conservative upper bound, atomically reject over-budget work, then settle actual usage. Enforce maximum iterations/calls/tokens/currency/time even when price data is missing. Rate-table updates are versioned; historical costs do not silently change.

Phase 13 implements the workspace-level reserve/settle/release path (`domain/budgets.py`, `infrastructure/budget_repositories.py`, `application/budget_service.py`), wired into `ToolRuntime.invoke_for_claim` around every tool call. `BudgetUsageRepository.try_reserve` is a single conditional `UPDATE ... WHERE requests_used + %s <= max_requests ... RETURNING id` — atomic under concurrency by construction, verified by a dedicated race test (`tests/test_budgets.py::test_concurrent_reservations_never_exceed_the_daily_ceiling`) that fires 20 concurrent reservation attempts against a ceiling of 5 and asserts exactly 5 succeed. An idempotent replay (an already-succeeded tool invocation reused via its action hash) never reserves twice. A workspace's default auto-provisioned policy caps `max_currency_minor_per_day` at zero, so no component can spend real money without an explicit higher policy — matching the zero-cost default everywhere else.

The default development and demo rate card assigns zero monetary charge to deterministic fake providers while still recording tokens, calls, attempts, and synthetic latency so the budget machinery is exercised. A live provider rate card is inactive unless an operator deliberately selects an opt-in profile. Cost telemetry must never be presented as an invoice or production estimate unless backed by the named provider and measured run.

## Zero-cost operating profile

The mandatory portfolio profile uses local PostgreSQL, local Redis, local API/web/workers, deterministic model and third-party adapters, local MCP servers, local evaluation reports, and a local OpenTelemetry-compatible sink. It requires no domain, cloud account, LangSmith account, billing credentials, paid observability account, or large model download. Optional self-hosted components must be documented with resource bounds and may not become prerequisites for core demonstrations.

Default tests, CI, evaluations, and `pnpm demo` must fail closed if a live-provider or cloud-provisioning path is requested without an explicit opt-in flag. Infrastructure-as-code validation and planning may run locally; apply/provision/destroy commands are outside the default demo and require explicit user approval. See [Zero-cost development and demo](zero-cost-demo.md).

## Resource-efficiency rules

Use small deterministic fixtures, targeted tests, sampled/redacted trace payloads, retention tiers, no required local model downloads, and only PostgreSQL/Redis as initial local services. Do not retain every raw prompt forever or retry providers blindly.
