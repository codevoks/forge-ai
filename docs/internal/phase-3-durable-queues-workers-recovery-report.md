# Phase 3 — Durable queues, workers, and recovery completion report

## Scope completed

Implemented the durable asynchronous execution layer for deterministic workflow tasks: transactional outbox dispatch, Redis Streams queue adapter, deterministic in-memory queue for fault tests, inbox deduplication, atomic task claims, attempt leases/fencing, bounded retries/backoff, checkpoints, dead letters, explicit run cancellation, operator recovery scan, dead-letter inspection/requeue, local worker lifecycle, and web visibility into worker state.

## Product changes

- Added `outbox_messages`, `inbox_messages`, `checkpoints`, and `dead_letters`.
- Extended `runs`, `tasks`, and `task_attempts` with cancellation, retry, lease, fencing, worker, heartbeat, and safe error metadata.
- Added the `QueuePort` interface, Redis Streams implementation, and deterministic in-memory queue.
- Added outbox dispatcher, worker consumer, retry policy, recovery scanner, deterministic task executor, and graceful worker loop.
- Changed run creation/readiness to enqueue ready work through the transactional outbox.
- Added `/v1/runs/{run_id}:cancel`, `/v1/operations/worker-state`, `/v1/operations/recovery:scan`, `/v1/operations/dead-letters`, and `/v1/operations/dead-letters/{dead_letter_id}:requeue`.
- Updated the local demo path to start PostgreSQL, Redis, API, web, and worker services with external integrations disabled.
- Updated the web UI to show durable worker-plane state, recovery scan results, cancellation, and sanitized dead-letter recovery.

## Security classification

| Area | Status | Evidence |
| --- | --- | --- |
| Tenant/workspace isolation for queue state | Protected and verified | RLS blocks outbox visibility without actor scope; operation queries run under actor scope. |
| Recovery/operator authorization | Protected and verified | Recovery scan and dead-letter inspection/requeue require `run.recover`; viewers are denied. |
| Duplicate delivery/replay abuse | Protected and verified | Inbox deduplication plus task claim predicates produce one authoritative outcome. |
| Stale worker overwrite | Protected and verified | Attempt completion requires matching attempt ID, fencing token, and unexpired lease. |
| Redis data loss | Protected and verified | PostgreSQL recovery scan republishes ready tasks that have no unpublished outbox. |
| Retry abuse | Protected and verified | Retry policy is bounded by max attempts and stores retry state durably. |
| Dead-letter payload leakage | Protected and verified | Dead letters expose sanitized error summaries, not task input, secrets, or raw external payloads. |
| Cancellation race | Implemented but needing deeper final validation | Workers check run state before claim/result; later tool/model interruption needs deeper validation when external effects exist. |
| Prompt/tool/MCP injection | Not applicable yet | No model, tool, retrieval, MCP, or external content execution exists in this phase. |
| Live provider/billing risk | Protected and verified | Default config and demo force external integrations disabled; paid providers are not part of the path. |

## Validation evidence

- `pnpm generate:types` — passed.
- `pnpm --filter @forge/api exec ruff check src tests` — passed.
- `pnpm --filter @forge/api exec mypy src` — passed.
- `pnpm --filter @forge/api test` — passed with 25 selected tests.
- `pnpm --filter @forge/api test:security` — passed with 15 selected tests.
- `pnpm --filter @forge/worker lint` — passed.
- `pnpm --filter @forge/worker test` — passed.
- `pnpm db:migrate && pnpm db:seed && pnpm generate:types && pnpm test && pnpm test:security && pnpm lint && pnpm typecheck && pnpm build && node scripts/check-public-files.mjs` — passed.
- `pnpm --filter @forge/api demo:recovery` — passed and demonstrated Redis-loss recovery, stale-lease fencing, and sanitized dead-letter requeue.

## Zero-cost evidence

The default path uses local PostgreSQL, local Redis, local API/web/worker processes, and deterministic task execution. The in-memory queue is used only for isolated fault tests. No paid model API, managed queue, Temporal Cloud, managed database, purchased domain, cloud worker, or billable observability service is required to build, test, evaluate, or demonstrate this phase.

## Demonstration evidence

The required demonstration exercises both UI and non-UI behavior:

1. Web UI loads the durable worker plane, creates a run, and shows worker-driven task/event/checkpoint progress.
2. Recovery demonstration uses real PostgreSQL plus Redis and proves queued work can be republished after Redis message loss.
3. Lease/fencing demonstration proves stale worker completion is rejected and recovery can make work eligible again.
4. Dead-letter demonstration proves permanent deterministic failure creates a sanitized dead letter and operator requeue is audited.

Actual non-UI recovery demo output:

```text
{"action": "redis_loss_recovery", "result": {"published_after_recovery": 2, "published_before_loss": 2, "recovery": {"due_retries": 0, "expired_leases": 0, "republished_ready_tasks": 2}, "stream_length_before_loss": 2, "terminal_status": "succeeded"}}
{"action": "stale_lease_fencing", "result": {"recovery": {"due_retries": 0, "expired_leases": 1, "republished_ready_tasks": 0}, "stale_commit_accepted": false, "terminal_status_after_recovery": "succeeded"}}
{"action": "dead_letter_requeue", "result": {"dead_letter_reason": "permanent_failure", "failed_status": "failed", "sanitized_payload_keys": ["error_message", "error_type"], "status_after_requeue": "running"}}
```

Actual UI demo state showed Alice Admin with `run.recover`, worker-plane counts, a created durable run in `succeeded`, all four workflow tasks in `succeeded`, four checkpoints, and ordered execution events including `task.claimed`, `task.succeeded`, and `run.succeeded`.

## Intentional limitations

- Deterministic task execution remains a local fake external boundary; model providers, tool execution, approvals, MCP, and multi-agent behavior are deferred.
- Worker heartbeat extension, tenant fairness scheduling, and advanced backpressure metrics are represented by contracts and bounded local behavior, but deeper tuning remains evidence-gated.
- `POST /v1/runs/{run_id}:advance` remains available only as a local debugging/learning fallback.
- Redis authentication/TLS and production secret wiring are production-path concerns, not required for the zero-cost local demo.

## Completion mapping

This report is paired with the exact completion commit tagged `phase-3` after final demonstration and remote verification.
