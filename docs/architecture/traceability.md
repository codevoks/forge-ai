# Requirement traceability

This matrix prevents capabilities from disappearing between phase handoffs. Detailed acceptance and learning gates live in the linked phase specifications.

| Required capability/knowledge | Architecture contract | Delivery phase(s) |
|---|---|---|
| Product/functional/non-functional requirements, actors, tenancy | requirements, system architecture | 0; materialized 1–2 |
| Deterministic workflow vs agent vs agentic vs multi-agent | architecture map, domain model | 0, 7, 12 |
| Python, TypeScript, SQL; Next.js/React/FastAPI/Pydantic/asyncio | system architecture | 1 onward |
| Authentication, tenancy, RBAC/capabilities, RLS | security/data contracts | 1 |
| Explicit run/step/task/attempt state and DAG invariants | domain model | 2 |
| Queues/workers, delivery, retry/backoff, DLQ, transactions, concurrency, locks | failure model | 3 |
| Idempotency, leases/fencing, checkpoints, recovery, cancellation, backpressure, shutdown | failure model | 3 |
| Typed tools, schemas, permissions, risk, timeout/retry/idempotency | data/security contracts | 4 |
| Structured outputs, provider abstraction, planning/DAG validation/replanning | domain/data contracts | 5 |
| Context, provenance, compaction, token budgets, explicit memory taxonomy | domain/security contracts | 5, 7 |
| Human approval and prompt/indirect/tool-output injection defenses | security threat model | 6 |
| Exact-action approval binding, separation of duties, approval expiry/rejection, secret-reference redaction, SSRF-ready URL denial | security threat model, data contracts, failure model | 6 |
| Privilege/secret/SSRF/replay/denial-of-wallet/runaway-loop controls | security threat model | 6; hardened 13 |
| Bounded agent loop and termination | domain model | 7 |
| LangGraph nodes/edges/reducers/tools/checkpoints/interrupts/comparison | decisions Q-004 | 8 |
| Fake models, golden/adversarial/failure scenarios and behavioral/live eval separation | requirements/decisions | 9 |
| Plan/tool/task/permission/approval/hallucination/cost/latency metrics | scale/cost contract | 9 |
| Event history, causal debugging, safe deterministic/simulation replay | failure/data contracts | 10 |
| MCP client/server/discovery/schema/invocation/auth/trust; owner-built server | decisions/ports | 11 |
| Router/supervisor/handoff/parallelism/isolation/aggregation/failure comparison | decisions Q-006 | 12 |
| Temporal evaluation/integration criteria | decisions Q-005 | 13 |
| OpenTelemetry, Langfuse, trace propagation | scale/observability contract | 10, 13 |
| Hierarchical cost/rate budgets | scale/cost contract | 7; completed 13 |
| Docker, GitHub Actions, and optional AWS/Terraform/Bedrock production path | decisions Q-003/Q-010 | 1 local/CI baseline; 13 optional production design |
| INR 0 local development/demo, deterministic external-boundary fakes, billable-path opt-in guard | zero-cost demo, decisions D-019/D-020 | every phase; consolidated 13 |
| 100x scale, SLO/RPO/RTO, load/failure/restore hardening | scale/failure contracts | 13 |
| Clean modular boundaries and refactoring gates | AGENTS/system architecture | every phase |
| 3–6 private exercises, quizzes, reconstruction, cumulative assessment | phase contracts/gate rules | every phase |
| Explain/design/implement/debug/defend hiring standard | requirements/phase gates | every phase; final 13 |
| Private owner education in natural Roman-script Hinglish; public engineering artifacts in professional English | AGENTS/phase gate contract | every phase |

Anything added later must enter this matrix with an owner phase, security/failure implications, test evidence, and learning evidence.
