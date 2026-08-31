# Failure, concurrency, and recovery model

## Delivery semantics

The queue provides at-least-once delivery: a message may be received more than once, including concurrently after a lease expires. PostgreSQL state decides whether work is still eligible. “Exactly once” is not a queue setting; for internal state it is approximated with transactions and uniqueness, while external effects require provider idempotency or reconciliation.

The transactional outbox closes the database-to-queue dual-write gap. The dispatcher may publish twice if it crashes after publish but before marking the row, so every consumer must deduplicate and still make handlers idempotent.

## Idempotency layers

1. **API:** scope + client idempotency key + request hash stores the prior response/resource.
2. **Message:** handler + message ID inbox uniqueness prevents duplicate message processing after a committed result.
3. **Task:** conditional claim and one-active-attempt constraint prevent ordinary concurrent ownership; fencing rejects stale workers.
4. **Logical operation:** stable key such as `tenant/run/task/tool/action_hash` survives attempt retries.
5. **Provider effect:** send the stable key when supported and record provider operation ID.
6. **Reconciliation:** if timeout/crash leaves the outcome ambiguous, query provider status or require operator resolution; never blindly repeat a non-idempotent high-risk effect.

Example: before sending an email, persist an authorized invocation with logical key. Use a provider idempotency key if offered. If the worker crashes after the provider accepts but before Forge records success, mark/recover as `OUTCOME_UNKNOWN`; reconcile by provider ID/message lookup. Without provider support there is no mathematical duplicate guarantee, so automatic retry is forbidden or the tool must be redesigned around a controlled outbox/provider.

## Retry policy

- Retry only normalized transient failures and safe/idempotent operations.
- Exponential backoff with full jitter, bounded attempts, maximum elapsed retry window, and provider `Retry-After` support.
- Persist `next_attempt_at`, error class, attempt count, and safe summary; never spin in memory.
- Invalid input, auth, policy denial, exhausted budget, and deterministic schema failure are not transient.
- Terminal retry exhaustion creates a dead-letter record and operator-visible failure; replay is a new audited command.
- Circuit breaking and tenant/provider bulkheads arrive when measurements justify them, but per-tenant concurrency limits exist from the first distributed worker.

## Claiming and concurrency

Ready-task claims use a short transaction with `FOR UPDATE SKIP LOCKED` (or equivalent conditional update), creating an attempt and lease/fencing token atomically. Workers heartbeat only while executing bounded calls. Result commits require the current attempt ID and fencing token; a stale worker cannot overwrite recovery work.

Optimistic concurrency (`version`) is the default for user/API mutations. Pessimistic row locking is restricted to short scheduler/approval/budget invariants. Advisory/distributed locks are not a substitute for constraints and conditional updates.

Dependency readiness is derived transactionally after predecessor completion, with a uniqueness constraint on task identity and an idempotent “make ready” operation. Multiple predecessor completions may race safely.

## Failure matrix

| Failure | Required behavior | Evidence/test |
|---|---|---|
| API dies before commit | no visible resource/job | transaction rollback test |
| API dies after commit before response | client retry returns same resource | idempotency integration test |
| Dispatcher dies around publish | message eventually appears, duplicates safe | crash-window test |
| Worker dies before effect | lease expires and retry claims | kill/recovery test |
| Worker dies after effect | provider dedupe or `OUTCOME_UNKNOWN` reconciliation | fault-injection fake provider |
| Duplicate/concurrent message | one authoritative transition/effect | concurrency test |
| Redis unavailable/restarted | commands persist; execution pauses and recovers | outage test |
| PostgreSQL unavailable | fail closed; no queue-only state progression | outage test |
| Model malformed/hallucinates tool | schema rejection, bounded correction/failure | fake-model scenarios |
| Provider rate limit | normalized backoff without tenant starvation | clock-controlled test |
| Approval requested | task moves to `waiting_approval`; worker stops before effect; queue message is acknowledged only after durable suspension | approval suspension test |
| Approval expires or changes | exact action cannot execute; expired request fails closed; binding mismatch rejects decision | race/security test |
| Cancellation races with claim | no new unsafe work; active work converges | barrier concurrency test |
| Process receives shutdown | stop claims, finish/abort bounded unit, release/expire safely | lifecycle test |
| Trace exporter fails | execution continues with bounded buffer/drop metric | adapter test |

## Cancellation

The current implementation supports explicit run cancellation through a persisted command. A cancellation records `cancellation_requested_at`, `cancelled_by`, and a safe reason, moves the run to `cancelled`, cancels tasks that have not reached a terminal result, and appends cancellation events. Workers re-check run status before claim and before result commit, so queued messages for cancelled work are skipped safely.

The fuller `cancelling -> cancelled` convergence model remains the production target for later interruptible model/tool calls. Cooperative cancellation cannot unsend an external effect. Interruptible adapters receive deadlines/cancel signals; non-interruptible calls finish and their results are recorded, but no downstream work starts.

## Backpressure and fairness

- Admission control rejects/defers work when tenant budgets, global queue depth, or provider capacity exceed limits.
- Separate workload queues and worker pools prevent slow model/effect calls from starving control tasks.
- Per-tenant in-flight/token/request limits plus round-robin/weighted fairness prevent noisy neighbors.
- Workers use bounded concurrency, bounded payloads, database connection pools, and queue prefetch.
- Autoscaling signals use oldest-message age and service time, not depth alone.
- When overloaded, preserve cancel/approval/status paths and shed low-priority new work explicitly.

## Checkpoints and recovery

Checkpoints currently occur after successful deterministic task execution and after each bounded agent iteration. Deterministic task checkpoints include the task result plus the attempt/fencing identity. Agent checkpoints include schema version, run/task/attempt/iteration identity, decision type/status, context hash, counters snapshot, evidence references, and the next legal action. Recovery scans are bounded and run under the worker service principal. They:

- expire stale running attempts whose leases elapsed;
- mark those attempts `abandoned`;
- return eligible tasks to `ready`;
- promote due `retry_wait` tasks;
- republish ready tasks that have no unpublished outbox message, including after Redis data loss.

Model/tool phases add checkpoints after validated plan creation and each authorized tool result. Recovery revalidates current policy, cancellation, approval, tool version, and schema before resuming. Bounded agent recovery is deterministic because persisted iterations, evidence hashes, model-call summaries, and budget counters reconstruct the last safe boundary; an abandoned attempt can be reclaimed and will continue from the recorded iteration count instead of spinning in memory.

## Replay semantics

- **State reconstruction:** fold recorded transitions in tests/audits to verify projections.
- **Decision replay:** feed captured sanitized inputs to deterministic fakes or a selected model and compare decisions.
- **Simulation replay:** replace tools with recorded/stub results; default mode.
- **Effect replay:** off by default; requires new authorization/approval/idempotency scope and produces new lineage.

Replay never pretends nondeterministic model output is bit-identical and never silently reuses expired authorization.

## Approval suspension and recovery

Approval suspension is a committed runtime state, not an in-memory worker pause. The worker records the invocation intent and approval request in PostgreSQL, marks the attempt/task as `waiting_approval`, acknowledges the queue message, and exits without invoking the adapter. Approval later revalidates run/task/invocation state, current approver capability, request version, expiry, and binding hash. A successful decision moves the task back to `ready`, marks the invocation `authorized`, and emits a new outbox message. A rejected or expired decision marks the invocation `policy_denied` and fails the run. If Redis is lost while an approval is pending, PostgreSQL still contains the waiting state; the approval decision creates a fresh outbox message.
