# Forge AI architecture map

This directory is the stable contract for implementation. Phase specifications describe increments; these documents describe decisions that must remain coherent across increments.

## Read order

1. [Requirements](requirements.md): product boundary, actors, use cases, and quality targets.
2. [System architecture](system-architecture.md): process boundaries, control/data flow, and module ownership.
3. [Visual guide](visual-guide.md): system topology, durable execution, policy control, and lifecycle diagrams.
4. [Domain and workflow model](domain-workflow-model.md): terminology, state machines, invariants, and execution semantics.
5. [Data and API contracts](data-api-contracts.md): durable records, transaction boundaries, APIs, events, and ports.
6. [Failure model](failure-model.md): delivery, concurrency, retries, recovery, cancellation, and replay.
7. [Security threat model](security-threat-model.md): assets, trust boundaries, threats, and required controls.
8. [Scale, observability, and cost](scale-observability-cost.md): workloads, signals, budgets, and scaling path.
9. [Zero-cost development and demo](zero-cost-demo.md): mandatory local demo path, opt-in integration boundary, and phase-by-phase substitutions.
10. [Architecture decisions](decisions.md): settled choices, rejected alternatives, and evidence-gated decisions.
11. [Requirement traceability](traceability.md): where every required capability and learning outcome is delivered.
12. [Phase roadmap](../phases/README.md): phase gates and focused implementation specifications.

## System thesis

Forge turns a tenant-scoped objective into a durable run. A deterministic runtime persists and schedules bounded tasks. Models may propose structured plans and tool calls, but code validates them against identity, policy, budgets, state, and approval. Workers execute authorized effects at least once while idempotency records prevent or expose duplicates. The resulting state and append-only evidence allow inspection, recovery, evaluation, and safe simulation.

## Architectural vocabulary

| Form | Control decisions | Best fit | Forge use |
|---|---|---|---|
| Deterministic workflow | Code-authored graph and branches | Known, auditable processes | Durable runtime and policy envelope |
| AI agent | Model chooses the next action in a loop | Open-ended decisions with bounded tools | Planner/executor inside hard limits |
| Agentic workflow | Code-authored skeleton containing model decisions | Most production AI automation | Primary Forge execution style |
| Multi-agent system | Multiple model roles coordinate or compete | Decomposable work where measurement proves value | Late, optional execution strategy |

These labels describe decision ownership, not marketing. A model call inside a workflow does not make the whole system autonomous.
