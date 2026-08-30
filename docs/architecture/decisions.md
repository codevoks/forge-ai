# Cross-phase architecture decisions

Status meanings: **Accepted** is binding until an ADR supersedes it; **Evidence-gated** fixes an interface and experiment but not the final technology.

| ID | Status | Decision | Why / consequence |
|---|---|---|---|
| D-001 | Accepted | Modular monolith with separately deployable web, API, worker | Preserves transaction clarity and learning; scale processes independently; extract only from evidence. |
| D-002 | Accepted | PostgreSQL is authoritative; Redis is queue/cache/rate coordination only | Durable relational invariants and auditability beat split-brain state. Redis loss delays work but does not lose acknowledged workflow state. |
| D-003 | Accepted | Current-state tables plus append-only execution events, not full event sourcing | Simple operational reads with audit/replay evidence. Events and projections commit together; event folding is verification, not the only recovery path. |
| D-004 | Accepted | Transactional outbox + at-least-once consumers | Avoids DB/queue dual-write loss. Duplicates are normal and handlers must be idempotent. |
| D-005 | Accepted | DAGs for user/template/planner work; loops live inside bounded state machines | Cycle-free dependency scheduling is understandable and testable; agent iteration remains explicit without arbitrary graph liveness problems. |
| D-006 | Accepted | Immutable versioned workflow, plan, tool, policy, and model configuration snapshots | Reproducibility and safe in-flight behavior; replans/changes append rather than rewrite history. Emergency policy may only tighten execution. |
| D-007 | Accepted | Code owns authz, risk, approval, budgets, validation, and termination | LLMs are untrusted/nondeterministic and cannot be a security boundary. |
| D-008 | Accepted | Approval binds exact canonical action and is distinct from authorization | Prevents bait-and-switch and privilege amplification; action changes require new approval. |
| D-009 | Accepted | External effects use intent ledger + stable idempotency key + reconciliation | Exactly-once effects cannot be promised across an external boundary. Unknown outcomes must be visible, not blindly retried. |
| D-010 | Accepted | UUIDv7 IDs, UTC time, integer aggregate versions, relational ownership | Cross-language opaque IDs with temporal locality; optimistic concurrency and tenant constraints are first class. |
| D-011 | Accepted | Versioned REST/OpenAPI plus polling/event cursor initially | Broad tooling, generated TS types, easy debugging. SSE is a later UI optimization; commands remain asynchronous. |
| D-012 | Accepted | OIDC authentication; API validates access token; RBAC plus capabilities | Avoid custom auth and centralize enforcement. Concrete IdP is replaceable and selected by deployment evidence. |
| D-013 | Accepted | Strict ports for model, queue, tool, workflow engine, secrets, telemetry | Prevents SDK leakage and enables deterministic fakes/meaningful comparisons. Do not generalize beyond these real variation points. |
| D-014 | Accepted | Custom educational runtime precedes LangGraph and Temporal | Owner learns state, scheduling, checkpoints, retries, and interruption before frameworks abstract them. |
| D-015 | Accepted | Trust/provenance labels and explicit memory categories | Prevents external content/context from becoming ambient authority and avoids magical memory. |
| D-016 | Accepted | Safe replay is simulation by default | Debugging cannot silently repeat side effects or reuse stale authorization. |
| D-017 | Accepted | Three separate validation lanes | Deterministic tests, offline behavioral evals, and opt-in live-model evals answer different questions and produce non-interchangeable evidence. |
| D-018 | Accepted | Tenant context is structural across persistence, jobs, cache, telemetry | Prevents late, partial tenancy retrofits and IDOR leakage. RLS is defense in depth, not a replacement for scoped services. |
| D-019 | Accepted | Zero-cost local development and portfolio demonstration is a permanent default architecture profile | Every Forge-owned durability, security, and orchestration mechanism runs for INR 0; only unavoidable external provider boundaries may use deterministic fakes. Potentially billable integrations are explicit opt-ins and cannot be exercised by default tests, CI, or demo commands. |
| D-020 | Accepted | Production-capable integrations and zero-cost demonstration adapters share narrow ports but separate configuration profiles | Preserves hiring-value architecture without making cloud accounts, paid providers, or large local models prerequisites. Evidence from a fake/local profile must not be mislabeled as live-provider or managed-cloud evidence. |

## Evidence-gated decisions

### Q-001 Redis queue implementation

The `QueuePort`, outbox, inbox, lease, and job envelope are fixed. Phase 3 should first implement a small Redis Streams adapter because pending entries and claiming expose at-least-once mechanics. Before production hardening, benchmark operational behavior against a mature Python queue library. Choose based on crash recovery, delayed retry, fairness, visibility, observability, maintenance, and measured throughput—not feature count. Do not place authoritative state in either option.

### Q-002 Identity provider

OIDC/JWT contracts and roles are fixed. Phase 1 must provide a local deterministic issuer/validator fixture sufficient for the complete zero-cost demo; a hosted-compatible adapter remains optional. Select Cognito/Auth0/Clerk/etc. only after deployment environment, B2B organization support, pricing, token claims, local testability, and operational ownership are known. Do not couple domain identities to vendor schemas or make a hosted tenant a test prerequisite.

### Q-003 Model providers and Bedrock

The provider-neutral structured interface and normalized usage/errors are fixed. A deterministic fake is the mandatory default and must cover all development, evaluation, and portfolio scenarios. Phase 5 may add a live adapter only as an explicit opt-in based on account access, structured-output/tool support, latency, price, and evaluation results. Bedrock is optional and requires separate approval before any call or provisioning.

### Q-004 LangGraph execution ownership

Phase 8 must compare custom and LangGraph implementations using identical scenarios, persistence/policy/tools, failure tests, complexity, trace quality, and recovery semantics. LangGraph may own agent-loop orchestration, but Forge remains authoritative for tenancy, approvals, effects, budgets, and audit. Adoption breadth follows evidence.

### Q-005 Temporal adoption

Phase 13 runs a free local/self-hosted spike and architecture review. Temporal Cloud is not required. Adopt only if durable timers, long-lived workflow history, signals, cancellation, retry operations, or developer/operational burden materially improve after including migration, infrastructure, determinism constraints, data duplication, and team learning cost. A no-adoption decision is valid.

### Q-006 Multi-agent default

No multi-agent default. Phase 12 compares a single agentic workflow against parallel specialists plus synthesizer on a frozen dataset, permissions, budgets, and models. Adopt per workflow only if task success/robustness gains justify latency, cost, coordination, and error propagation.

### Q-007 Policy engine

Use explicit typed Python policies initially. Benchmark OPA/Cedar or a policy DSL only when policy authorship, explanation, audit, or cross-service reuse becomes painful. The stable decision interface, deny-by-default semantics, and tests remain.

### Q-008 Search/vector storage and durable knowledge

No vector database in the base architecture. Add retrieval only when a concrete Phase 7+ use case and evaluation dataset demonstrate benefit. Start with PostgreSQL metadata plus object storage/search appropriate to measured corpus/query needs; every knowledge source needs ACL, freshness, provenance, retention, and deletion.

### Q-009 Event streaming to the browser

Polling with event cursors is the correctness baseline. Add SSE in Phase 10 if user-experience measurement warrants it. WebSockets require bidirectional low-latency need and are not currently justified.

### Q-010 Infrastructure topology

An optional AWS production topology may include container service, managed PostgreSQL, managed Redis, object storage, secret manager, and an OpenTelemetry backend, but ECS versus EKS, RDS versus Aurora, and Temporal adoption remain workload/team/cost choices. Phase 13 can author and validate Terraform and document the deployment without applying it. No cloud resource is provisioned without explicit user approval; the complete portfolio demo remains local.

## Change procedure

Any implementation that conflicts with an accepted decision must add a numbered ADR containing context, alternatives, security/failure/scaling impact, migration and rollback plan, and evidence. Phase convenience alone is insufficient.
