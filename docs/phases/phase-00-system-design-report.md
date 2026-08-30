# Phase 0 — System design report

## System Design

### Decisions

- Modular monolith with separately deployable web, API, and worker processes.
- PostgreSQL authoritative current state plus append-only execution events; Redis is disposable transport/cache.
- Transactional outbox, at-least-once consumers, layered idempotency, leases and fencing.
- Immutable versioned DAGs for planned work and bounded state machines for loops.
- Code-enforced authorization, risk, exact-action approval, budgets, validation, and termination.
- Structural tenant/workspace scope, trust/provenance labels, secret references, and safe simulation replay.
- Stable ports isolate queue, model, tool, MCP, workflow-engine, secret, and telemetry choices.
- Zero-cost local development and portfolio demonstration is a permanent default profile; production-capable integrations remain optional behind the same narrow ports.

### Tradeoffs

The design accepts explicit schema/state-machine/outbox complexity to gain durability, auditability, and teachable failure semantics. It defers microservices and framework ownership to preserve transaction clarity. Polling precedes SSE, DAGs exclude arbitrary cycles, and exactly-once external effects are deliberately not claimed. Deterministic external-boundary fakes trade managed-provider fidelity for reproducibility and zero cost, without replacing real Forge persistence, scheduling, policy, approval, or recovery behavior.

### Failure implications

Redis or telemetry loss pauses/degrades execution without losing authoritative runs. PostgreSQL loss fails closed. Duplicate work is expected and tested. External crash ambiguity becomes `OUTCOME_UNKNOWN` and reconciliation rather than a blind retry. Cancellation is cooperative and cannot undo completed effects.

### Scaling implications

API and workload workers scale separately; per-tenant admission/fairness and bounded concurrency protect shared dependencies. First expected 100x limits are database connections/locks/event growth, queue lag, provider quotas/tail latency, telemetry cost, and budget/fairness contention. Extraction or Temporal adoption requires measured evidence.

## Product

- Implementation: documentation and design artifacts only, as required; no application scaffold or production code.
- Visuals: system topology, durable execution, policy gates, bounded autonomy, and canonical state lifecycles are documented as Mermaid diagrams.
- Tests: completeness/headings/file-boundary audit performed.
- Security tests: threat/control matrix and future adversarial/tenant/race tests specified.
- Failure tests: crash-window matrix and future deterministic fault tests specified.
- Validation: all 14 descriptively named phase specifications include scope, learning, architecture, modules, data, APIs/interfaces, security, failures, testing, acceptance, exercises, system-design expectations, and deferrals.
- Refactoring: canonical terminology and decisions were consolidated into stable architecture contracts rather than duplicated across phase narratives.

## Learning

- Lessons: self-contained Phase 0 concepts and walkthroughs created externally.
- Interview questions: explain/design/debug/defend bank created.
- Coding exercises: five private exercises specified; not completed by the owner yet.
- Reconstruction test: closed-note system design, implementation fragment, and oral defense created.
- Cumulative revision: master concept map and spaced-repetition rules created.
- Assessment status: not tested; product completion does not imply learning readiness.

## Resources

- Dependencies/services installed or started: none.
- Disk implications: Markdown documentation only; no model downloads, containers, databases, or fixtures.
- Future local baseline: PostgreSQL and Redis only when their owning phases begin.
- Permanent demo baseline: no paid subscription, cloud account, billing credential, purchased domain, trial credit, or large local model download is required.

## Git Safety

- The private learning vault is physically outside the Forge project directory.
- `.local-learning/` and common secret/build/cache files are ignored.
- This project directory is not currently a Git repository, so tracking/secrets-in-history cannot yet be verified. Run a tracking and secret scan immediately after initialization and at every phase gate.
- Suggested first commit/tag after repository initialization and review: `docs: complete phase 0 architecture blueprint`, tag `phase-0-blueprint`.

PRODUCT GATE: **PASS**

HIRING-READINESS LEARNING GATE: **NOT TESTED**

Architecture amendment recorded on 2026-08-27: the zero-cost development and demonstration contract is binding across Phases 1–13. No Phase 1 application code is part of this report.

Stop here. Phase 1 requires fresh explicit authorization.
