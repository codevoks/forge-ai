# Phase 3 — Durable queues, workers, and recovery

## Scope

Implement transactional outbox dispatch, Redis Streams `QueuePort`, inbox deduplication, atomic task claims, leases/fencing, bounded retries/backoff/jitter, dead letters, checkpoints, cancellation convergence, recovery scanner, graceful shutdown, tenant fairness and backpressure. Tasks remain deterministic fixtures.

## Concepts being learned

At-least-once delivery, dual-write problem, outbox/inbox, idempotency layers, leases/fencing, retry classification, dead-letter operations, cancellation races, backpressure, graceful shutdown, failure injection.

## Architecture changes

API commits outbox only; dispatcher publishes versioned minimal envelopes; workload consumers reload PostgreSQL and atomically claim; recovery reclaims expired work; clock/random/queue are ports for deterministic tests. Separate control and test-work queues/pools.

## Components/modules

Outbox dispatcher; Redis Streams adapter and deterministic fake; consumer supervisor; claim/heartbeat/lease service; retry policy; checkpoint store; cancellation service; dead-letter/requeue command; recovery scanner; worker lifecycle/health/metrics.

## Data model changes

`outbox_messages`, `inbox_messages`, `checkpoints`, `dead_letters`; task-attempt lease/fencing/error/retry fields; run cancellation request/deadline fields; indexes for unpublished/due/ready/expired scans; retention/cleanup markers.

## APIs and important interfaces

Run cancel; operator inspect/retry dead letter with new audit lineage; worker health. `QueuePort`, `JobEnvelope`, `RetryPolicy`, `TaskClaimer`, `Lease`, `CheckpointStore`, `RecoveryService`, injectable `Clock`/jitter source. Queue messages never carry task inputs/secrets.

## Security requirements

Redis authenticated/private/TLS in production; DB revalidates envelope scope/eligibility; worker/service principal least privilege; tenant-aware queue limits; dead-letter payload sanitized; requeue capability audited; cancellation cannot bypass effect reconciliation.

## Failure scenarios

All crash windows before/after commit/publish/claim/effectless result/ack; duplicate and concurrent delivery; lease expiry with live stale worker; Redis loss; DB loss; poison message; retry storm; tenant starvation; shutdown during claim; clock skew; cancellation at every boundary.

## Testing strategy

Deterministic clock retry tests; real Postgres/Redis integration; process-kill fault tests; duplicate/concurrency barrier tests; stale fencing rejection; outbox crash-window test; Redis restart recovery; cancellation convergence; bounded pool/backpressure/fairness; dead-letter/operator audit tests.

## Acceptance criteria

No acknowledged run is lost when Redis is flushed; duplicate jobs produce one authoritative outcome; stale workers cannot commit; retries follow persisted policy and exhaust to dead letter; cancellation converges without new work; worker drains safely; queue adapter can be replaced through tests.

## Learning objectives

Build a minimal durable worker; narrate every crash window; distinguish retry safety from idempotency; debug queue lag/leases and design backpressure.

## Coding exercises (private)

1. Exponential backoff with full jitter and fake clock.
2. Atomic SQL claim and fencing check.
3. Outbox dispatcher crash simulation.
4. Idempotent consumer under 50 duplicate messages.
5. Cooperative cancellation race.
6. Queue-age capacity calculation.

## System-design knowledge expected

Explain why Redis is not authoritative, why outbox still duplicates, claim/lease/fencing mechanics, dead-letter/replay semantics, connection/concurrency bounds, fair scheduling, and exactly-once impossibility.

## Zero-cost development and demo path

Run Redis and workers locally, preferably through the demo Docker profile, while PostgreSQL remains authoritative. Use the real outbox, Redis Streams adapter, leases, fencing, retries, dead letters, checkpoints, cancellation, and recovery scanner; use the deterministic queue fake only for isolated timing/fault tests. The demo must visibly survive duplicate delivery, worker interruption, and Redis data loss without a managed queue or worker platform.

## Explicitly deferred

External side effects (Phase 4), model retries (Phase 5), approval suspension (Phase 6), LangGraph/Temporal, production autoscaling. Queue-library replacement remains evidence-gated after the educational adapter is measured.
