# Requirements and product boundary

## Product objective

Forge accepts an objective, constructs or selects a bounded workflow, gathers evidence with permitted tools, pauses for required approval, and produces inspectable remediation proposals or authorized effects. The simultaneous learning objective is a first-class deliverable: the owner must be able to reconstruct and defend the important primitives.

## Actors and tenancy

- **Tenant**: billing and primary isolation boundary.
- **Workspace**: collaboration, integrations, policy, and run boundary within a tenant.
- **User**: authenticated human; may hold tenant and workspace roles.
- **Service principal**: narrowly scoped API/worker/integration identity.
- **Approver**: human with both approval permission and separation-of-duty eligibility.
- **Operator**: starts/cancels/retries runs and inspects failures.
- **Auditor/viewer**: read-only access to allowed evidence and events.

Initial roles are `tenant_admin`, `workspace_admin`, `operator`, `approver`, and `viewer`. Tool grants and approval eligibility are capabilities layered on RBAC, not new ad-hoc roles.

## Functional requirements

1. Create, inspect, list, cancel, and retry tenant-scoped runs with idempotent APIs.
2. Define immutable, versioned workflow templates and instantiate their steps as run tasks.
3. Persist run/task/attempt state, dependencies, checkpoints, events, budgets, and provenance.
4. Atomically schedule ready work, execute it at least once, retry safely, dead-letter terminal failures, and recover abandoned claims.
5. Register versioned typed tools; enforce schemas, permissions, risk, budgets, timeouts, and output limits.
6. Invoke interchangeable LLM providers through structured requests/responses; validate plans and calls before use.
7. Require code-enforced human approval for policy-selected effects and bind approval to exact action intent.
8. Support a bounded agentic loop with explicit context, evidence, stop conditions, and replanning rules.
9. Offer an equivalent LangGraph path without changing domain/security contracts.
10. Evaluate deterministic correctness, offline agent behavior, opt-in live-model quality, cost, and latency separately.
11. Preserve a queryable execution history and support simulation/replay without silently repeating external effects.
12. Discover and invoke permitted MCP tools through the same policy/tool envelope.
13. Compare single-workflow and multi-agent strategies on the same scenarios and metrics.
14. Export traces/metrics/logs, enforce rate/cost budgets, and provide a documented optional AWS deployment path.
15. Provide a reproducible local portfolio demo that exercises the real Forge runtime and security architecture with deterministic external-boundary fakes and no billing credentials.

## Non-functional requirements

- **Correctness:** illegal state transitions are rejected; dependency and approval invariants are transactional.
- **Durability:** acknowledged state survives process/Redis loss; PostgreSQL backup/restore is tested before production.
- **Delivery:** internal work is at least once; duplicate handlers are safe; external uncertainty is explicit.
- **Isolation:** no cross-tenant access through APIs, jobs, events, caches, traces, exports, or integration credentials.
- **Security:** deny by default, least privilege, auditable policy decisions, no model-controlled authorization.
- **Availability target (initial production):** 99.5% monthly API availability excluding declared maintenance; asynchronous execution can degrade independently.
- **Recovery targets:** design target RPO <= 5 minutes and RTO <= 60 minutes after backups/operations exist; these are not claims until drills pass.
- **Latency targets:** p95 read API < 500 ms and accepted command API < 1 s under baseline load; model/tool latency is reported separately.
- **Scalability:** horizontally scalable stateless API/workers; no global in-process scheduler or tenant-blind queue.
- **Auditability:** every security-relevant decision and state transition records actor, tenant, cause, correlation, and sanitized metadata.
- **Accessibility/UX:** keyboard-operable UI, explicit state/failure/approval language, and no hidden autonomous actions.
- **Portability:** provider and infrastructure adapters are replaceable, while PostgreSQL semantics are an intentional dependency.
- **Zero-cost demonstrability:** the complete default development, test, evaluation, and portfolio demo path costs INR 0; potentially billable providers and infrastructure are explicit opt-ins and cannot be reached by default tests or CI.

## Core user journeys

1. An operator submits an objective with a workflow/template, allowed-tool set, and budgets.
2. Forge validates identity/policy, persists the run, records an event, and schedules initial work atomically.
3. A worker claims work, builds scoped context, optionally requests a structured model decision, and validates it.
4. Read-only tools execute immediately when permitted. High-risk effects create a pending approval and suspend the task.
5. An eligible approver reviews exact arguments/evidence, approves or rejects, and execution resumes or terminates.
6. The user watches progress, investigates failures, cancels safely, or retries only an allowed boundary.
7. Results include evidence/provenance, not an unsupported narrative.

## Explicit non-goals through Phase 13

- General-purpose autonomous computer use, arbitrary shell execution, or untrusted code execution.
- Exactly-once claims for third-party side effects.
- Arbitrary cyclic user-authored graphs; validated DAG plans plus bounded internal loops are sufficient.
- Cross-region active-active writes, custom identity provider, marketplace, billing engine, or mobile client.
- Vague long-term “memory”; only ownership-scoped runtime state, context, knowledge, preferences, or episodes with lifecycle rules.
- Replacing human organizational judgment with model-generated security decisions.

## Product success evidence

The repository must pass phase acceptance tests, but the project is complete only when the owner also passes explain/design/implement/debug/defend gates and a final reconstruction of a simplified Forge without consulting production code.
