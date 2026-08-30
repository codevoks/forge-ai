# Data and API contracts

## Durable data groups

The following are conceptual tables; migrations are introduced in the owning phase.

| Group | Records | Important constraints |
|---|---|---|
| Identity | tenants, workspaces, users, memberships, service_principals | composite tenant/workspace FKs; normalized external subject uniqueness |
| Control | workflow_templates, workflow_versions, tool_definitions, tool_versions, integration_connections, policy_versions, budget_policies | immutable published versions; secrets stored only as references |
| Execution | objectives, runs, plan_versions, tasks, task_dependencies, task_attempts, checkpoints | tenant scope, versions, one active attempt, DAG uniqueness |
| AI/tools | model_calls, tool_invocations, evidence_items | provider-neutral status/usage; trust/provenance; payload size/retention |
| Approval | approval_requests, approval_decisions | action hash, expiry, eligible actor, one terminal decision |
| Reliability | idempotency_records, inbox_messages, outbox_messages, dead_letters, leases | unique logical keys; retry schedule; claim fencing |
| Audit | execution_events, security_audit_events | append-only application permissions; sanitized metadata |

All primary identifiers are application-generated UUIDv7 values. Timestamps are UTC `timestamptz`. Mutable aggregates use integer `version` for optimistic concurrency. JSONB is allowed for versioned schemas, provider-neutral payloads, and evidence; relationships, states, ownership, uniqueness, money, and query-critical fields remain relational.

## Transaction boundaries

One transaction must cover each of the following:

- idempotent command lookup/create + aggregate mutation + execution event + outbox;
- run creation + objective snapshot + tasks/dependencies + initial readiness;
- task claim + attempt creation + lease/fencing token;
- attempt result + task/run transition + checkpoint + budget settlement + event/outbox;
- approval decision + action-hash validation + invocation/task transition;
- tool intent + budget reservation before effect; result settlement happens later because external calls cannot join the transaction.

Keep transactions short and never hold database locks across queue, model, tool, MCP, or network calls.

## Repository and unit-of-work ports

```text
UnitOfWork
  begin / commit / rollback
  runs, tasks, attempts, approvals, tools, events, outbox, budgets

RunRepository.get_for_update(scope, run_id)
TaskRepository.claim_ready(scope, worker_id, lease_until) -> Claim | None
EventRepository.append(aggregate, type, actor, cause, sanitized_payload)
OutboxRepository.add(topic, partition_key, envelope)
IdempotencyRepository.begin(scope, operation_key, request_hash)
```

Application services own transaction orchestration. Repositories do persistence only; domain transition functions are pure and independently testable.

## HTTP contract

- Versioned JSON REST under `/v1`; generated OpenAPI is the source for browser client types.
- Browser uses secure HTTP-only same-site session cookies at the web boundary; API receives/verifies a short-lived OIDC access token. Non-browser clients use scoped bearer tokens.
- Every route derives tenant/workspace from verified actor context plus explicit path IDs; never trust tenant IDs in bodies.
- Mutating create/command endpoints require `Idempotency-Key`; reusing a key with a different canonical request hash returns `409`.
- Optimistic updates accept `If-Match`/resource version and return `409` on conflict.
- Errors use a stable problem-details envelope: `code`, safe `message`, `correlation_id`, optional field errors, and retryability. Internal/provider text is not returned raw.
- Cursor pagination is mandatory for collections. Filters are allowlisted and tenant-scoped.
- Initial progress transport is polling plus cursor-based `GET /v1/runs/{id}/events`; SSE may be added in Phase 10. Commands never wait for full execution.

Core endpoint families:

```text
POST/GET /v1/runs; GET /v1/runs/{run_id}
POST /v1/runs/{run_id}:cancel
GET /v1/runs/{run_id}/tasks
GET /v1/runs/{run_id}/events
GET /v1/approvals; POST /v1/approvals/{id}:approve|:reject
GET /v1/tools; POST /v1/workflows; POST /v1/workflows/{id}/versions
POST /v1/evaluations; GET /v1/evaluations/{id}
```

Administrative registration endpoints appear only with their owning phase and capability checks.

## Asynchronous envelope

Every outbox/queue message has `message_id`, `schema_version`, `type`, `occurred_at`, `tenant_id`, `workspace_id`, `aggregate_type`, `aggregate_id`, `correlation_id`, `causation_id`, `trace_context`, and a minimal payload of durable IDs. Consumers reject unknown major schema versions, validate scope against database state, and deduplicate on `message_id` plus handler name.

Queues are partitioned/routed by workload and risk (`control`, `model`, `tool_read`, `tool_effect`, `maintenance`) with tenant-aware fair scheduling and concurrency limits. Message priority is bounded to prevent starvation.

## Stable service interfaces

- `AuthorizationService.decide(actor, action, resource) -> PolicyDecision`
- `RiskPolicy.classify(tool_version, canonical_args, context) -> RiskDecision`
- `ApprovalPolicy.requirement(actor, risk, action) -> ApprovalRequirement`
- `BudgetService.reserve/settle/release(scope, operation, estimate/actual)`
- `Planner.plan(PlanningRequest) -> StructuredPlanResult`
- `PlanValidator.validate(plan, envelope) -> ValidatedPlan | violations`
- `ModelProvider.complete(StructuredModelRequest) -> ModelResult`
- `ToolRegistry.resolve(name, version) -> ToolDefinition`
- `ToolExecutor.invoke(AuthorizedInvocation) -> ToolResult`
- `QueuePort.publish/consume/ack/nack/extend_lease`
- `CheckpointStore.save/load`
- `TelemetryPort` and `Clock`/`IdGenerator` for deterministic tests.

Provider errors are normalized into `invalid_request`, `auth`, `rate_limited`, `transient`, `timeout`, `policy_blocked`, and `unknown`; only explicitly retryable classes enter backoff.

## Schema evolution

Database migrations are forward-only and expand/migrate/contract for live changes. Event/job/API payloads carry versions and use tolerant readers within a declared compatibility window. Published workflow/tool/plan versions are immutable. Breaking tool schemas create a new tool version; in-flight runs remain pinned.

