# Phase roadmap and gates

Implement exactly one narrow phase at a time. Each phase specification is a handoff contract, not permission to begin it.

Product progression and learning assessment are independent tracks. Explicit user authorization permits the next product phase even when the hiring-readiness learning gate remains `NOT TESTED` or `IN PROGRESS`; neither status lowers implementation, validation, security, or demonstration standards.

The complete default development, test, evaluation, and portfolio demonstration path must cost INR 0. Each phase uses real Forge-owned persistence, coordination, policy, recovery, and security behavior while replacing only unavoidable paid/external boundaries with deterministic fakes. Potentially billable providers and cloud infrastructure are explicit opt-ins and require current user approval. The binding cross-phase profile and substitution matrix are in [Zero-cost development and demo](../architecture/zero-cost-demo.md).

Specification and report filenames always include the two-digit phase number and covered scope. The completed Phase 00 report is [Phase 00 — System design report](phase-00-system-design-report.md).

| Phase specification | Covered scope | Depends on |
|---|---|---|
| [Phase 00 — System design](phase-00-system-design.md) | Requirements, architecture, threat/failure model, learning examination | none |
| [Phase 01 — Foundation, authentication, tenancy, and RBAC](phase-01-foundation-authentication-tenancy-rbac.md) | Monorepo, web/API skeleton, authentication, tenancy, RBAC | Phase 00 gate |
| [Phase 02 — Deterministic workflow domain](phase-02-deterministic-workflow-domain.md) | Persisted workflow domain, DAGs, state machines, invariants | Phase 01 |
| [Phase 03 — Durable queues, workers, and recovery](phase-03-durable-queues-workers-recovery.md) | Outbox, queues/workers, retries, idempotency, checkpoints, cancellation/recovery | Phase 02 |
| [Phase 04 — Typed tool runtime](phase-04-typed-tool-runtime.md) | Typed deterministic tools, permissions, risk, validation, invocation ledger | Phase 03 |
| [Phase 05 — LLM provider and structured planning](phase-05-llm-provider-structured-planning.md) | Provider-neutral models, structured planner, bounded validated DAGs | Phase 04 |
| [Phase 06 — Human approval and AI security](phase-06-human-approval-ai-security.md) | Exact-action approval, guardrails, trust boundaries, adversarial controls | Phase 05 |
| [Phase 07 — Bounded agentic workflow](phase-07-bounded-agentic-workflow.md) | End-to-end planner/runtime/tools/approval agentic workflow | Phase 06 |
| [Phase 08 — LangGraph implementation and comparison](phase-08-langgraph-implementation-comparison.md) | LangGraph parity implementation and evidence-based comparison | Phase 07 |
| [Phase 09 — Evaluation, failure injection, and LangChain interoperability](phase-09-evaluation-failure-injection.md) | Evaluation harness, fake models, adversarial suites, failure injection, LangChain provider/prompt/tool/structured-output interop, initial LangSmith experiment/export seam | Phase 08 |
| [Phase 10 — Execution history, debugging, replay, and trace export](phase-10-execution-history-debugging-replay.md) | Event history, debugger, safe replay, live progress, LangGraph state inspection, OTel/LangSmith trace-linking seam | Phase 09 |
| [Phase 11 — MCP interoperability](phase-11-mcp-interoperability.md) | MCP client/server discovery and invocation behind tool policy | Phase 10 |
| [Phase 12 — Multi-agent patterns](phase-12-multi-agent-patterns.md) | Parallel specialists, routing/supervision, measured single-vs-multi comparison | Phase 11 |
| [Phase 13 — Temporal, LangSmith observability, and cloud hardening](phase-13-temporal-observability-cloud-hardening.md) | Temporal decision, LangSmith/OTel observability, budgets, AWS/Terraform, scale hardening | Phase 12 |

## Universal phase exit procedure

1. Refactor the phase-owned boundaries and update architecture/ADR documentation.
2. Run focused deterministic, integration, tenant/security, failure, and concurrency tests; run behavioral/live evals only where relevant and label them.
3. Verify no secrets or private educational artifacts are inside/tracked by the repository, and prove the default commands made no live or potentially billable calls.
4. Complete private phase learning files, 3–6 coding exercises, cumulative quiz, and reconstruction test.
5. Update the private Learning Vault `current-state.md` with verified mastery, weaknesses, completed exercises, both gate statuses, and exactly one next action so a fresh chat can resume safely.
6. Demonstrate the implemented phase with reproducible commands, APIs, browser flows, database/state inspection, tests, and deterministic failure/security simulations appropriate to its scope. The demo must run without billing credentials; claims without evidence do not pass.
7. Produce a phase report covering system design, product, learning, resources, Git safety, exact demo evidence, reproduction steps, limitations, and the next phase.
8. Set `PRODUCT GATE: PASS|FAIL` and `HIRING-READINESS LEARNING GATE: NOT TESTED|IN PROGRESS|PASS` independently.
9. Stop. Continue only after the user explicitly authorizes the next phase.

## Phase specification contract

Each file explicitly lists scope, concepts, architecture and data changes, modules, APIs/interfaces, security, failures, tests, acceptance, learning objectives, exercises, expected system-design knowledge, and deferrals. Where the implementation discovers contrary evidence, write an ADR rather than silently changing the cross-phase contract.

## LangChain, LangGraph, and LangSmith final coverage gate

The remaining roadmap may enhance subsystems originally delivered in earlier phases, but historical phase tags and completion reports remain unchanged. Final completion requires executed evidence, not package presence:

| Technology | Natural subsystem | Remaining implementation location | Required evidence |
|---|---|---|---|
| LangChain | Model/provider, prompt/message, structured-output, tool interoperability, and composition around the Phase 5 planning/model boundary | Phase 9 | Offline deterministic LangChain-backed adapter/composition path, parity/regression tests, security tests proving Forge remains authoritative, demo/report output, and zero-cost fallback |
| LangGraph | Stateful agent orchestration, graph state, nodes, reducers, checkpoints, interrupts/HITL, and state inspection around the Phase 7 bounded-agent boundary | Already introduced in Phase 8; evaluated further in Phase 9 and debugged/replayed further in Phase 10 | Executed LangGraph run path, checkpoint evidence, parity/adversarial tests, user-visible demo, and proof that Forge remains the control plane |
| LangSmith | Evaluation/tracing/experiment observability around model calls, tool calls, agent iterations, datasets, and regression runs | Phase 9 initial experiment/export seam; Phase 10 trace correlation; Phase 13 final optional live/self-hosted adapter validation | Implemented opt-in adapter, redaction/tenant/security/exporter-outage tests, local offline fallback demo, and explicitly approved live/self-hosted evidence if available |

## Permanent learning-language contract

All repository specifications and reports remain professional English. For every phase, the separately stored private learning package and all owner-facing teaching, quizzes, interview practice, assessment feedback, system-design/security explanations, debugging discussions, and reconstruction discussions use natural Roman-script Hinglish. Standard technical terminology remains in English and must not be awkwardly translated.

The private `current-state.md` is updated after every learning session as well as every phase; it is the resume contract for future chats and records only demonstrated progress.
