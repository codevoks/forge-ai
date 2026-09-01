# Phase 8 — LangGraph implementation and comparison report

This internal report preserves Phase 8 completion evidence without exposing phase history in the product UI or primary README.

## Scope completed

- Added a selectable workflow-engine strategy for bounded agent tasks with `custom` as the default and `langgraph` as an explicit per-run option.
- Implemented a local open-source LangGraph `StateGraph` path for the existing bounded agent workflow.
- Preserved Forge authority for tenant scope, run/task claims, tool grants, strict schemas, approvals, budgets, state transitions, evidence, and audit events.
- Added PostgreSQL-backed, RLS-protected `workflow_engine_checkpoints` for sanitized LangGraph comparison/debug evidence.
- Added API and UI inspection for run engine metadata and LangGraph checkpoint mirrors.
- Added deterministic custom-vs-LangGraph parity, failure, approval, and adversarial demo coverage.

## Architecture changes

Phase 8 introduced the following implementation-grade seams:

- `WorkflowEngineKind` and pinned engine versions in `forge_api.domain.workflow_engine`.
- `LangGraphAgentRuntime` as an alternate implementation behind the existing worker execution boundary.
- `ForgeLangGraphCheckpointer`, which mirrors sanitized LangGraph checkpoint metadata into Forge-owned PostgreSQL records.
- `WorkflowEngineCheckpointRepository` and `WorkflowEngineService` for tenant-scoped checkpoint reads.
- `GET /v1/runs/{run_id}/engine-checkpoints` for read-only engine comparison evidence.
- `runs.engine_kind`, `runs.engine_version`, `runs.engine_metadata`, and `workflow_engine_checkpoints` migration support.

LangGraph does not own authorization, approvals, effect execution, task state, run state, recovery policy, or tenant isolation.

## Security classification

| Area | Classification | Evidence |
| --- | --- | --- |
| LangGraph engine authority boundary | Protected and verified | Unauthorized `billing.charge_customer v99` proposal is rejected before adapter execution |
| LangGraph checkpoint tenant isolation | Protected and verified | Checkpoints are hidden without transaction scope and require run authorization through the API |
| LangGraph bounded autonomy | Protected and verified | Step-limit scenario fails closed without uncontrolled looping |
| LangGraph prompt-injection containment | Protected and verified | Prompt-injected objective remains inside granted local tools and records untrusted provenance |
| LangGraph approval interrupt boundary | Protected and verified | High-risk simulated effect suspends at Forge approval and resumes only after eligible approval |
| Hosted LangGraph/cloud checkpointing | Not applicable yet | Default path uses the local open-source library only |

## Zero-cost evidence

- Default model path remains deterministic fake model.
- Default external integration mode remains disabled.
- `pnpm demo:langgraph` runs locally and reports `paid_provider_calls: 0`.
- No hosted LangGraph service, live model provider, paid tracing product, or cloud infrastructure is required.

## Validation evidence

Recorded during Phase 8 closeout:

- `pnpm db:migrate`
- `pnpm db:seed`
- `pnpm --filter @forge/api lint`
- `pnpm generate:types`
- `pnpm demo:langgraph`
- Focused LangGraph parity/security tests: `../../.venv/bin/pytest tests/test_langgraph_engine.py -q`

The final phase closeout reruns the full phase gate and records the exact final results in the conversation handoff.

## Demonstration evidence

The Phase 8 demo must show:

- UI engine selector using the established dark charcoal and electric violet design system.
- A real LangGraph run completing through the worker path.
- Engine metadata and mirrored checkpoint rows visible in the UI.
- CLI evidence for custom/LangGraph parity, step-limit safe failure, unauthorized-tool denial, prompt-injection containment, approval interrupt/resume, and zero paid provider calls.

## Deferred items

- Making LangGraph the default engine is deferred until Phase 9 comparison/evaluation evidence.
- Hosted LangGraph services, remote checkpoint stores, and managed tracing remain out of scope.
- Multi-agent LangGraph topologies are deferred to the multi-agent phase.
- Temporal comparison remains deferred to the dedicated workflow-engine evaluation phase.
- Large-scale checkpoint performance benchmarking is deferred until a measured need exists.

## Git closeout

- Completion commit: commit tagged `phase-8`
- Tag: `phase-8`
- Remote verification: required at phase closeout
- Working tree: clean verification required at phase closeout
