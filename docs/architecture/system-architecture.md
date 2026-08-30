# System architecture

## Derivation

The dominant forces are durable asynchronous work, risky external effects, tenant isolation, explainability, and learning the mechanics before adopting orchestration frameworks. They lead to one deployable system with strict internal boundaries, not premature microservices.

The [visual guide](visual-guide.md) shows this topology, the durable execution sequence, the model-to-effect policy boundary, and the run/task lifecycles. Read the diagrams alongside the invariants below; arrows show communication, not authority.

## Deployable boundaries

- `apps/web`: Next.js UI and same-origin browser facade. It presents state; it never decides authorization or workflow transitions.
- `apps/api`: FastAPI command/query boundary, JWT verification, actor construction, policy calls, and transaction orchestration.
- `apps/worker`: queue consumers, outbox dispatcher, abandoned-work recovery, task execution, and graceful shutdown.
- `packages/config`: validated, non-secret configuration contracts shared where language permits; generated schemas instead of runtime coupling across Python/TypeScript.
- `packages/shared-types`: OpenAPI-derived TypeScript client/types and stable cross-process envelopes. Python domain types remain owned by the backend.

Python backend code begins within the owning app and is extracted only when two deployables truly share a stable concept. Intended internal modules are:

```text
domain/          entities, value objects, state transitions, invariants
application/     use cases and transaction orchestration
policy/          authorization, risk, approval, budget decisions
runtime/         readiness, scheduling, context, bounded execution
planner/         provider-neutral structured planning and validation
tools/           registry and invocation envelope
ports/           repository, queue, model, secret, clock, id factories
infrastructure/  PostgreSQL, Redis, providers, MCP, telemetry adapters
api/             HTTP schemas/routes/dependencies
```

Dependencies point inward: infrastructure and delivery depend on application/domain contracts; domain imports no web, database, queue, model, or provider SDK.

## Command path

1. API verifies issuer/audience/signature/expiry, constructs `ActorContext`, and resolves tenant/workspace membership.
2. Request schema and idempotency key are validated before application use case execution.
3. Within one PostgreSQL transaction the use case locks/checks relevant versions, applies domain transitions, writes current state plus execution events, and appends outbox messages.
4. The API returns the committed resource. It does not directly enqueue work.
5. A dispatcher publishes outbox records and marks them published. Crash windows can duplicate publication by design.

## Worker path

1. Consumer receives a tenant-tagged job and checks its durable identity/deduplication record.
2. It atomically claims the task/attempt using status, lease, and version predicates.
3. It re-evaluates cancellation, policy, approval, and budgets against current authoritative state.
4. It performs one bounded unit, recording invocation intent before any external effect.
5. It validates/sanitizes output, persists outcome/event/outbox atomically, then acknowledges the queue message.
6. On timeout/crash, lease recovery makes the unit eligible again. Idempotency controls determine whether an effect may be retried, reconciled, or must remain `outcome_unknown`.

## Control plane versus execution plane

- **Control plane:** identity, tenant/workspace administration, workflow/tool registration, policies, credentials references, budgets, approvals.
- **Execution plane:** runs, tasks, attempts, planning/model calls, tool invocations, events, scheduling, recovery.

They share the initial database and services but have separate modules, permissions, quotas, and audit categories. This creates an extraction seam without paying microservice consistency costs early.

## Consistency choices

- Strong transactional consistency for state transitions, dependency readiness, claims, approval consumption, budget reservations, tool-intent records, and outbox creation.
- Eventual consistency for queue publication, UI projections/search, metrics, trace export, and Langfuse export.
- No distributed transaction with model/tool providers. Use intent records, idempotency keys, bounded retry, status reconciliation, and compensating actions where meaningful.
- Read-your-writes comes from the primary database initially. Replica reads, if added, must expose staleness and never drive security or scheduling decisions.

## Extension seams

- `QueuePort`: in-process deterministic fake then Redis Streams; Temporal adapter only after evidence.
- `ModelProvider`: deterministic fake, OpenAI/Bedrock adapters, normalized usage/errors.
- `Tool`: local deterministic implementations and MCP proxy share one validated invocation contract.
- `WorkflowEngine`: custom explicit runtime and LangGraph implementation share domain repositories, policy, tools, and events.
- `PolicyEngine`: code-owned interfaces; start with explicit Python policies, benchmark a policy DSL/OPA only if complexity demands it.

## Why not microservices now

The transaction boundary across runs, tasks, approvals, budgets, and outbox is valuable. A modular monolith preserves it, makes failure reasoning visible, lowers operational load, and still permits API and workers to scale separately. Extraction requires measured contention, team ownership, or security isolation—not fashion.
