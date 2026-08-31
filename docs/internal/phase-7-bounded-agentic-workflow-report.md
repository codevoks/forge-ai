# Phase 7 — Bounded agentic workflow report

## Product gate

Status: PASS after implementation, validation, and real user-visible demonstration.

## Implemented scope

- Added `agent` workflow/task kind inside the existing deterministic run envelope.
- Added bounded agent runtime with explicit iterations, model-call ledger entries, checkpoints, budgets, no-progress/invalid-decision limits, tool-call validation, and citation validation.
- Added `agent_iterations` as the durable per-iteration ledger with RLS.
- Extended run tool grants so agent task `allowed_tools` are snapshotted at run creation and cannot be expanded by model output.
- Added `/v1/runs/{run_id}/agent-iterations` inspection API.
- Added deterministic `forge-fake-agent-v1` behavior for success, step-limit, unauthorized-tool, prompt-injection, unsupported-citation, and replan scenarios.
- Added web UI support for Bounded Agent Demo and visible iteration/checkpoint inspection.
- Added `pnpm demo:agentic` deterministic CLI demonstration.
- Updated OpenAPI/shared TypeScript contracts and architecture documentation.

## Security classification

| Area | Classification | Evidence |
|---|---|---|
| Agent tool authority | Protected and verified | `unauthorized_tool` rejects `billing.charge_customer v99` before adapter execution |
| Agent loop/runaway control | Protected and verified | `step_limit` stops at configured iteration bound and fails closed |
| Agent citation grounding | Protected and verified | Unsupported evidence citation is rejected |
| Prompt-injection containment | Protected and verified | Hostile objective uses only granted local tool and stores output as `untrusted_tool_output` |
| Tenant/RLS isolation | Protected and verified | Mallory cannot read Alice agent iterations; no-scope DB read returns no rows |
| Replanning | Implemented but needing deeper final validation | Replan request is recorded and fails closed; full immutable replan lineage remains deferred |
| Live provider behavior | Not applicable yet | Default agent model is deterministic fake; live providers remain disabled |

## Validation evidence

- `pnpm db:migrate` — passed.
- `pnpm db:seed` — passed.
- `../../.venv/bin/pytest tests/test_agent_runtime.py -q` — `6 passed`.
- `pnpm demo:agentic` — passed; showed success, step-limit failure, unauthorized-tool denial, prompt-injection containment, and `paid_provider_calls: 0`.
- `pnpm test` — passed; `42 passed, 33 deselected` for API plus web/worker/config/shared package tests.
- `pnpm test:security` — passed; `33 passed, 42 deselected` for API security plus web/security checks.
- `pnpm lint` — passed.
- `pnpm typecheck` — passed.
- `pnpm build` — passed after rerun outside sandbox because sandbox blocked Turbopack helper process/port binding.
- `node scripts/check-public-files.mjs` — passed.

## Demo evidence

CLI demo:

- `success`: run succeeded with two validated iterations: `tool_call` then `complete`, one evidence item, `trusted_local_fixture`.
- `step_limit`: run failed safely after two validated tool-call iterations.
- `unauthorized_tool`: run failed safely; rejected `Tool billing.charge_customer v99 is not allowed.`
- `prompt_injection`: run succeeded using only `customer_reports.search`; evidence labeled `untrusted_tool_output`.
- `paid_provider_calls: 0`; `external_integrations: disabled`.

Browser demo:

- Local demo environment was started with `FORGE_EXTERNAL_INTEGRATIONS=disabled` and `FORGE_MODEL_PROVIDER=fake`.
- The web UI showed the Bounded Agent Demo workflow, run status, task status, agent iterations, model-call ledger entries, tool invocation/evidence panels, and worker/checkpoint counts.
- The demonstrated UI state showed the successful bounded agent path and the persisted iteration decisions.

## Architecture notes

- Agent iteration is a state machine inside a task; the workflow graph remains acyclic.
- Model output is non-authoritative. Forge application code validates schemas, exact tool grants, budgets, citations, and termination before acting.
- Each iteration persists before tool action, giving deterministic reconstruction evidence for debugging and future replay.
- Tool output remains untrusted data and cannot alter system policy, budgets, grants, or approval rules.

## Zero-cost proof

- Default provider: `fake`.
- External integrations: `disabled`.
- Agent/tool behavior used deterministic local implementations.
- No billing credentials were used or required.
- `pnpm demo:agentic` reported `paid_provider_calls: 0`.

## Limitations and deferrals

- LangGraph implementation/comparison remains deferred to Phase 8.
- Comprehensive evaluation harness remains deferred to Phase 9.
- Replay debugger remains deferred to Phase 10.
- MCP remains deferred to Phase 11.
- Multi-agent patterns remain deferred to Phase 12.
- Temporal/cloud/observability hardening remains deferred to Phase 13.
- Full execution-time replan lineage is not implemented in Phase 7; replan requests fail closed.

