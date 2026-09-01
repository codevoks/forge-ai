# Phase 9 — Evaluation, failure-injection, and LangChain interoperability harness report

This internal report preserves Phase 9 completion evidence without exposing phase history in the product UI or primary README.

## Scope completed

- Added persisted offline evaluation suites, cases, runs, case results, normalized metrics, and sanitized export records.
- Added `POST /v1/evaluations`, `GET /v1/evaluations`, and `GET /v1/evaluations/{evaluation_run_id}` with idempotency, authorization, and tenant-scoped reads.
- Added a LangChain-backed deterministic provider path (`langchain_fake`) around the prompt/message/runnable boundary while preserving Forge-owned schema, tool, DAG, cost, and policy validation.
- Preserved the existing custom and LangGraph engine paths and added evaluation cases that compare parity and safe failure behavior.
- Added a LangSmith export seam that produces a local sanitized artifact by default and fails closed for live export while external integrations are disabled.
- Added UI support for running and inspecting the offline evaluation harness using the established dark charcoal and electric violet visual system.
- Added `pnpm demo:evaluations` for deterministic zero-cost CLI demonstration evidence.

## Architecture changes

Phase 9 introduced these implementation-grade seams:

- `EvaluationService` as the application-level harness that invokes real Forge services under an authorized actor.
- `EvaluationRepository` and migration `009_evaluation_failure_injection.sql` for suite/result/metric/export persistence.
- `LangChainDeterministicModelProvider`, which composes LangChain prompt/runnable primitives with Forge's deterministic fake provider.
- `LangSmithEvaluationExporter`, which owns the optional LangSmith-shaped export seam and zero-cost local artifact mode.
- Web client types and UI panel for user-visible evaluation results.

LangChain, LangGraph, and LangSmith remain non-authoritative. Forge application code still enforces tenant scope, permissions, schemas, tool grants, approvals, budgets, state transitions, and security policy.

## Security classification

| Area | Classification | Evidence |
| --- | --- | --- |
| LangChain provider boundary | Protected and verified | `langchain_fake` cases pass only after Forge validates plan schema, DAG, and allowed tool versions |
| LangChain tool-authority expansion | Protected and verified | Hallucinated `billing.charge_customer v99` plan is rejected as unauthorized |
| Prompt-injection containment | Protected and verified | Prompt-injected objective remains inside allowed local tool projection |
| Evaluation execution authorization | Protected and verified | Viewer execution is denied with `evaluation_run_forbidden` |
| Evaluation tenant isolation | Protected and verified | Outsider reads return `evaluation_run_not_found` |
| LangGraph bounded failure | Protected and verified | Step-limit case fails closed with worker outcome `policy_denied` |
| LangSmith live export | Protected and verified for default profile | Local artifact mode records `live_export=false`; enabled mode fails closed without explicit external opt-in |
| Live model or hosted evaluator quality | Not applicable yet | No live provider, hosted grader, or account-backed LangSmith run was approved or executed |

## Zero-cost evidence

- Default external integration mode remains `disabled`.
- Default model/provider paths use deterministic fakes.
- Offline evaluation reports `paid_provider_calls: 0`.
- `langsmith_export_mode=local` records a local sanitized artifact.
- `langsmith_export_mode=enabled` returns `langsmith_export_disabled` without a live account or network call while external integrations are disabled.

## Validation evidence

Recorded during Phase 9 closeout:

- `pnpm db:migrate` — passed after correcting the evaluation-suite composite key.
- `pnpm db:seed` — passed with evaluation table cleanup included.
- `.venv/bin/pytest apps/api/tests/test_evaluations.py -q` — `7 passed`.
- `pnpm demo:evaluations` — passed and printed six passed cases, local LangSmith artifact, live LangSmith fail-closed response, and zero paid provider calls.
- `pnpm generate:types` — passed and regenerated OpenAPI-derived shared TypeScript types.
- `pnpm test` — passed: API `48 passed, 40 deselected`; web `1 passed`; worker `1 passed`; config/shared type package checks completed.
- `pnpm test:security` — passed: API `40 passed, 48 deselected`; web `1 passed`; package checks completed.
- `pnpm lint` — passed after formatting the evaluation demo import block.
- `pnpm typecheck` — passed across all workspace packages.
- `pnpm build` — passed across all workspace packages.
- `node scripts/check-public-files.mjs` — passed.

## Demonstration evidence

The Phase 9 demo showed:

- The local app was opened at `http://127.0.0.1:3000/` through the Codex browser panel.
- Browser-control automation could list the Forge tab but timed out while claiming it, so UI click automation could not be completed in this environment.
- The closest reproducible demo ran `pnpm demo:evaluations`, which exercised the same API endpoint used by the UI and printed a real persisted evaluation run with six passed cases.
- The demo output included LangChain provider evidence through `langchain_fake`, LangGraph parity/failure evidence, a local LangSmith-shaped artifact with `live_export=false`, fail-closed live LangSmith response `langsmith_export_disabled`, and `paid_provider_calls: 0`.

## Deferred items

- Account-backed LangSmith export remains optional and unverified until explicitly approved.
- Live-model and model-graded evaluation lanes remain opt-in and budget-capped.
- Statistical benchmark claims, live-provider quality claims, and hosted-evaluator claims remain deferred until measured evidence exists.
- Multi-agent evaluation datasets remain deferred to the multi-agent phase.
- Final integrated red-team audit remains required after all implementation phases.

## Git closeout

- Completion commit: commit tagged `phase-9`.
- Tag: `phase-9`.
- Remote verification: required at phase closeout.
- Working tree: clean verification required at phase closeout.
