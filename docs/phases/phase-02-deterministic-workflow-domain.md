# Phase 2 — Deterministic persisted workflow domain

## Scope

Implement immutable workflow-template versions, objective/run creation, task DAG instantiation, explicit run/task transitions, dependency readiness, current-state queries, transactional events, and pure deterministic in-process execution tests. No external queue, LLM, tool side effect, or agent framework.

## Concepts being learned

Aggregate/invariant design, state machines, DAG validation, transaction boundaries, relational modeling, optimistic/pessimistic concurrency, current state plus history, deterministic scheduling.

## Architecture changes

Add domain transition functions, application use cases, unit of work/repositories, DAG validator/readiness evaluator, and event writer. Commands mutate state/events atomically. A deterministic test driver invokes one ready task at a time without becoming production execution infrastructure.

## Components/modules

Workflow template registry/version publisher; plan-independent step definitions; objective/run/task/dependency/attempt value types; transition tables; scheduler readiness service; execution event catalog; run command/query routes and basic run graph UI.

## Data model changes

`workflow_templates`, `workflow_versions`, `workflow_steps`, `workflow_edges`, `objectives`, `runs`, `tasks`, `task_dependencies`, `task_attempts`, `execution_events`, initial `idempotency_records`; uniqueness, ownership, immutable published versions, versions/check constraints, one-active-attempt constraint.

## APIs and important interfaces

Workflow version create/publish/get; run create/get/list; task/event list; deterministic test-only command adapter. `TransitionResult`, `DAGValidator`, `ReadinessEvaluator`, repositories/UoW, `EventCatalog`. Run creation pins workflow/policy/tool-budget placeholders.

## Security requirements

Tenant-scoped workflow/run access; immutable snapshot prevents post-start substitution; objective and event payload size limits/redaction; workflow publication capability separate from run execution; server-derived ownership and actor audit.

## Failure scenarios

Cyclic/missing/oversized graph; concurrent predecessor completion; duplicate run creation; stale version transition; transaction rollback after partial graph insert; terminal-state mutation; corrupted/unsupported workflow version; cancellation command before workers exist.

## Testing strategy

Property/table tests for transitions and DAGs; database constraints; transaction rollback; concurrency barriers around readiness/claim simulation; event/current-state atomicity; tenant isolation; API idempotency; deterministic full DAG scenarios and graph UI smoke.

## Acceptance criteria

Invalid graphs/transitions cannot persist; a valid DAG runs deterministically through test driver with correct readiness; duplicate/racing commands create one result; every transition has one event in the same commit; state can be explained from tables/events; no Redis/model/tool dependency.

## Learning objectives

Implement state machine and topological scheduler independently; identify aggregate/transaction boundaries; explain event sourcing alternative and database-enforced invariants.

## Coding exercises (private)

1. Transition validator from a blank file.
2. DFS and Kahn cycle detection comparison.
3. Dependency readiness scheduler.
4. Concurrent predecessor completion test.
5. SQL schema/invariant review exercise.

## System-design knowledge expected

Defend step/task/attempt distinction, adjacency rows, DAG bounds, immutable versions/replanning, current state plus events, lock choices, and transaction contents.

## Zero-cost development and demo path

Use local PostgreSQL for the real schema, constraints, transactions, RLS context, concurrency, state transitions, DAG scheduling, and event/projection writes. In-memory test doubles may support unit tests but cannot replace database integration and race evidence. Extend the local demo with a seeded deterministic workflow that is inspectable through APIs and database state. No managed database or hosted workflow service is required.

## Explicitly deferred

Distributed queue/workers, retry/backoff/checkpoint recovery, real tools/model planning/approval, arbitrary conditions beyond a small deterministic typed set, event streaming/replay UI.
