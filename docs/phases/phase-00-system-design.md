# Phase 0 — System design

## Scope

Derive and freeze the product boundary, requirements, domain vocabulary, process/module architecture, data/API contracts, state and failure models, threat model, scale/cost assumptions, technology decisions, phase sequence, and learning assessment. No production application code, dependency installation, database, or service scaffold is allowed.

## Concepts being learned

Requirements-to-architecture derivation; deterministic workflow vs agent vs agentic workflow vs multi-agent; authoritative state; state machines and DAGs; transactions and consistency; queues and at-least-once delivery; idempotency; checkpoints; cancellation; trust boundaries; threat modeling; SLO/capacity/cost reasoning; framework adoption criteria.

## Architecture changes and artifacts

- Establish the modular-monolith topology and inward dependency rule.
- Define PostgreSQL authority, Redis non-authority, transactional outbox, worker claim/lease/fencing, current state plus append-only events.
- Define tenant/workspace/identity, objective/template/run/plan/task/attempt/tool/approval/evidence/event/budget concepts.
- Define REST, async envelope, ports, state machines, invariants, replay modes, observability propagation, and security axiom.
- Record accepted and evidence-gated decisions in `docs/architecture/`.

## Components/modules

Design-only boundaries: web, API, worker, domain, application, policy, runtime, planner, tools, ports, infrastructure, telemetry. Ownership and dependency direction are documented; none are implemented.

## Data model changes

No schema is created. Conceptual data groups, identifiers, ownership columns, versions, event/outbox records, constraints, retention needs, and transaction boundaries are specified in [data contracts](../architecture/data-api-contracts.md).

## APIs and important interfaces

Specify `/v1` resource/command families, idempotency/version/error/pagination rules, async envelope, repositories/unit-of-work, and policy/model/tool/queue/checkpoint/telemetry ports. No OpenAPI or executable interface is generated.

## Security requirements

Complete asset/trust-boundary/threat/control analysis. Prove that models cannot authorize, expand tools, approve, set budgets, or bypass termination. Require structural tenant scope, exact-action approval, secret references, trust labels, SSRF controls for later fetchers, safe replay, and denial-of-wallet controls.

## Failure scenarios

Analyze every crash window across API -> DB -> outbox -> queue -> worker -> model/tool; duplicate/concurrent delivery; effect outcome ambiguity; Redis/PostgreSQL/provider outage; stale lease; cancellation/approval races; telemetry loss; 100x overload. Document safe result and future test for each.

## Testing strategy

- Document consistency review: every requirement maps to a phase and acceptance gate.
- Invariant walkthrough using concrete success, duplicate, crash-after-effect, cancellation, approval, and cross-tenant scenarios.
- Architecture challenge review against the Phase 0 examination.
- Privacy verification that the learning vault is outside any repository and `.local-learning/` is ignored.
- Confirm repository contains documentation only and no production code.

## Acceptance criteria

- All architecture and phase documents exist and use one canonical vocabulary.
- Each Phase 0 design question can be answered from decisions and understood by the owner.
- Every later phase contains all required implementation/learning/test/deferral sections.
- Important cross-phase decisions are accepted or have a named evidence-gated experiment.
- A binding zero-cost profile and Phase 1–13 substitution matrix separate the real Forge core from deterministic external-boundary fakes and prevent default billable calls/provisioning.
- Threat/failure models include all prompt-required attacks and distributed failures.
- Private Phase 0 learning package and real examination exist outside the project.
- `PRODUCT GATE: PASS` may be set after artifact review. Learning remains `NOT TESTED` until the owner completes the examination and defense.

## Learning objectives

The owner can derive components from requirements, draw command/worker flows, explain why PostgreSQL is authoritative, reason through duplicate external effects, define transactional invariants, select DAGs/loops correctly, place approvals/security outside the model, and scale/backpressure the design verbally.

## Coding exercises (private, 3–6)

1. Pure state-transition validator with table-driven illegal transitions.
2. DAG cycle detection/topological ordering with node/fan-out bounds.
3. Transactional pseudocode for task claim plus fencing.
4. Idempotency ledger design for crash-after-email ambiguity.
5. Trace-context propagation across an asynchronous boundary.

These are scratch implementations outside Git and are not Forge production code.

## System-design knowledge expected from the owner

Defend modular monolith vs microservices; PostgreSQL vs Redis authority; outbox/inbox and at-least-once delivery; optimistic vs pessimistic concurrency; state projection plus events vs event sourcing; DAG vs arbitrary graph; cooperative cancellation; backpressure/fairness; safe replay; LangGraph/Temporal adoption thresholds; exact-action approvals; 100x bottlenecks; and what the zero-cost local/fake profile proves versus what requires live-provider or managed-cloud evidence.

## Zero-cost architecture amendment

The complete local development, deterministic test/evaluation, and portfolio demonstration path must cost INR 0. It uses the real Forge persistence, coordination, security, approval, recovery, replay, MCP, and multi-agent architecture with local PostgreSQL/Redis/workers and deterministic external-boundary fakes. Potentially billable models, hosted services, cloud resources, and deployment mutations are explicit opt-ins requiring current user approval. The binding profile, guard interfaces, visual, evidence rules, tradeoffs, and Phase 1–13 review are documented in [Zero-cost development and portfolio demonstration](../architecture/zero-cost-demo.md), decisions D-019/D-020, and each phase specification.

## Explicitly deferred

All scaffolding and executable code; exact dependencies/versions; IdP vendor; queue library outcome; concrete live model/provider; policy engine; vector search; LangGraph adoption breadth; multi-agent adoption; Temporal decision; AWS topology and any cloud provisioning. Their interfaces/experiments are fixed now, implementations remain in their named phases. Zero-cost equivalents are not deferred; they are mandatory within each owning phase.
