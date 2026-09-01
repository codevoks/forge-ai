# Phase 12 — Measured multi-agent patterns report

This internal report preserves Phase 12 completion evidence without exposing phase history in the product UI or primary README.

## Scope completed

- Added an explicit `strategy_kind` on `runs` (`single_agentic` default, `multi_agent_parallel` opt-in), mirroring the existing `engine_kind` pattern; no multi-agent default (decisions.md Q-006 unchanged).
- Added a deterministic, code-owned `Router` that narrows a multi-agent workflow's specialist steps to the objective-relevant ones by keyword match, enforced in application code before any task is persisted — never a model call, never a source of new authority.
- Represented specialists as ordinary `kind="agent"` workflow steps with their own `allowed_tools`/budgets/objective, isolated from siblings, fanning out and back in through the unchanged Phase 2 DAG scheduler (no new scheduler, queue, or task kind).
- Added `SpecialistAgentRuntime`, reusing the entire Phase 7 `AgentRuntime` decision loop unchanged; a specialist's safe termination becomes a soft `outcome=safe_failure` task success rather than a task failure, so a deterministic `SynthesizerRuntime` can aggregate a partial result from whichever specialists did succeed and fail the run closed only when none did.
- Closed a genuine cross-specialist evidence-isolation gap discovered while implementing this phase: `AgentRepository.recent_evidence` was scoped only to `run_id`, harmless for Phase 7's one-agent-per-run design but a real contamination path once multiple specialists share a run; it is now scoped to `task_id` too.
- Added a comparative evaluator (`MultiAgentComparisonService`) that runs one frozen local objective through both strategies and records task success, model/tool call counts, wall-clock elapsed seconds, and task status counts for each in a new `strategy_comparisons` table, with explicit no-cherry-picking/statistical caveats.
- Added `POST/GET /v1/multi-agent/comparisons` and extended `POST /v1/runs` with optional `strategy_kind`.
- Added a deterministic zero-cost `pnpm demo:multi-agent` path exercising every required scenario with zero paid calls.
- Added 36 new automated tests (`test_multi_agent_domain.py`, `test_multi_agent_runtime.py`, `test_multi_agent_security.py`), with zero regressions to the existing 173 Phase 1–11 tests.

## Architecture changes

Phase 12 introduced these implementation-grade contracts:

- `domain/multi_agent.py`: `ExecutionStrategyKind`, a code-owned `SPECIALIST_ROLES` catalog (mirroring the code-registered tool catalog pattern), `Router`/`RoutingDecision`, `SpecialistResult`/`SpecialistOutcome`, `SynthesisResult`/`AggregationPolicy`.
- `application/multi_agent_router.py`: `apply_router` filters a fetched workflow version's steps/edges to the router-selected specialists before `RunRepository.create_run` ever writes a task — the Forge authority boundary for delegation: the router's proposal is validated and enforced here, never trusted directly.
- `application/multi_agent_runtime.py`: `SpecialistAgentRuntime` (safe-termination-to-soft-result wrapping) and `SynthesizerRuntime` (deterministic aggregation over prerequisite tasks' own `tasks.result`, read via the existing `task_dependencies` edges — no parallel "handoff" storage).
- `application/multi_agent_comparison_service.py` and `infrastructure/multi_agent_repositories.py`: the comparative evaluator and its persistence.
- `RunRepository.create_run` gained optional `strategy_kind`/`strategy_version`/`strategy_metadata` parameters (defaults preserve every existing Phase 1–11 call site's behavior exactly) and now persists `tasks.agent_role` from each step's own input.
- The multi-agent synthesizer deliberately reuses the existing `kind="deterministic"` step kind (tagged via `input.mode="multi_agent_synthesize"`) rather than adding a new kind value — see migration 012's inline note: `workflow_steps_kind_check`/`tasks_kind_check` are unconditionally re-declared by migrations 004 and 007 on every replay (this project replays every migration file on every `pnpm db:migrate`, with no per-migration version tracking), so widening them would pass on a fresh database but fail on every subsequent replay once a row using the new value exists. This was caught and fixed during implementation, before it could affect a real repeated test/CI cycle.
- `RetryPolicy.NON_RETRYABLE_ERROR_TYPES` gained `multi_agent_synthesis_no_usable_results`, so an all-specialists-safe-failure case fails the run closed immediately instead of retrying a decision that immutable specialist results can never change.

## Security classification

| Area | Classification | Evidence |
| --- | --- | --- |
| Forged/unknown specialist role | Protected and verified | A workflow step naming a role outside the code-owned catalog returns `agent_role_unknown` before any task is persisted |
| Cross-specialist evidence isolation | Protected and verified | `evidence_items.task_id` is distinct per specialist in a completed multi-agent run; `recent_evidence` is task-scoped |
| Cross-specialist tool authority | Protected and verified | A specialist's task-level `allowed_tools` is enforced independently of what a sibling in the same run was granted |
| Router authority | Protected and verified | The router's selection is enforced by filtering the workflow graph in application code before persistence; routing is never a model call |
| Recursive delegation / runaway spawning | Not applicable — structurally prevented | The agent decision schema has no delegation/spawn primitive; specialists are fixed at publish time and bounded by `MAX_SPECIALISTS` |
| Cyclic delegation | Protected and verified | Rejected by the unchanged Phase 2 `DAGValidator` (`workflow_cycle`) |
| Synthesizer fabricated consensus | Protected and verified | The synthesizer is deterministic code over already-validated `SpecialistResult` payloads; it never calls a model |
| Partial-failure aggregation | Protected and verified | A safe-failed specialist yields `partial_failure=true` and is excluded; synthesis fails closed only when zero specialists produced a usable result |
| Cancellation propagation | Protected and verified | Cancelling mid-fan-out marks every pending specialist and the synthesizer `cancelled` via the unchanged Phase 3 cascade |
| RBAC and tenant isolation | Protected and verified | Multi-agent run creation and strategy comparisons require `run.create`; `strategy_comparisons` is RLS-scoped and hidden without transaction context |
| Approval bypass through delegation | Protected and verified | A specialist proposing a `simulated_effect` tool call suspends for exact-action approval exactly like a Phase 6 single-agent task |

## Zero-cost evidence

- Default external integration mode remains `disabled`; both strategies in the comparison run on the deterministic fake model and local tools only.
- `pnpm demo:multi-agent` reports `paid_provider_calls: 0` / `live_model_calls: 0` in every scenario, including the comparative evaluator.
- The comparative evaluator's `elapsed_seconds` figures are local wall-clock overhead only, explicitly labeled as not representative of live-model latency in the persisted `caveats` field.

## Validation evidence

Recorded during Phase 12 closeout:

- `pnpm --filter @forge/api db:migrate` — passed; migration `012_multi_agent_patterns.sql` applied cleanly, including a repeated-replay check (migrate → seed → migrate → seed → migrate all succeeded in sequence) that specifically exercises the kind-check-constraint replay hazard the migration's design note describes.
- `pnpm test` — passed: API `135 passed, 74 deselected` (108 pre-existing + 27 new); web/worker package checks completed.
- `pnpm test:security` — passed: API `74 passed, 135 deselected` (65 pre-existing + 9 new).
- `pnpm lint` — passed across all 5 workspace packages.
- `pnpm typecheck` — passed across all 5 workspace packages (mypy strict: 96 source files, 0 issues).
- `pnpm build` — passed (Python `compileall`, Next.js production build).
- `pnpm generate:types` — passed; OpenAPI export includes both new `/v1/multi-agent/*` routes and the `strategy_kind` field on `POST /v1/runs`; shared TypeScript types regenerated.
- `pnpm demo:multi-agent` — passed; see demonstration evidence below.
- `node scripts/check-public-files.mjs` — passed.
- `git diff --check` — passed (no whitespace issues).

## Demonstration evidence

`pnpm demo:multi-agent` output (abridged, one JSON line per scenario):

- **Router selection**: objective "Investigate why the API deployment is slow and customers are complaining." selected `deployment_specialist`/`customer_impact_specialist`, skipped `remediation_specialist`; only the selected specialists' tasks (plus the synthesizer) were created.
- **Parallel fan-out and synthesis**: both selected specialists succeeded with `distinct_specialist_evidence_tasks: 2` (evidence never shared between them), `partial_failure: false`, run `succeeded`.
- **Fallback routing**: a no-signal objective selected all 3 specialists (`fallback_selected_all: true`).
- **Approval-gated specialist**: the `remediation_specialist`'s `simulated_effect` ticket tool call suspended for exact-action approval and, once Ava approved, completed (`simulated_effect_invocation_status: succeeded`).
- **Partial failure**: one specialist safe-failed (budget exhaustion) while the other succeeded; the run still succeeded with `partial_failure: true` and `skipped_roles: ["deployment_specialist"]`.
- **Total failure**: both specialists safe-failed; the synthesizer had no usable result and the run failed closed (`terminal_status: failed`).
- **Cancellation mid-fan-out**: cancelling immediately after creation marked every specialist task and the synthesizer `cancelled`.
- **Forged role denial**: a workflow step naming an unrecognized role was rejected (`agent_role_unknown`, 422) before any task was created.
- **Comparative evaluator**: single-agentic used 1 tool call / 2 model calls / 1 succeeded task; multi-agent-parallel used 2 tool calls / 4 model calls / 3 succeeded tasks and took roughly 2× the wall-clock time on this machine — genuine, measured coordination-overhead evidence, with explicit caveats that this is one frozen local scenario, not a statistically powered study.
- Final summary line: `paid_provider_calls: 0`, `live_model_calls: 0`.

## Reproduction steps

```bash
pnpm install
pnpm db:up
pnpm db:migrate
pnpm demo:multi-agent
```

To inspect the underlying tests directly:

```bash
pnpm --filter @forge/api test -- tests/test_multi_agent_domain.py tests/test_multi_agent_runtime.py
pnpm --filter @forge/api test:security -- tests/test_multi_agent_security.py
```

## Limitations

- The router is a deterministic keyword matcher, not a model; an optional model-backed router behind the same `Router` interface remains a documented future extension (decisions.md Q-006), not implemented here — no multi-agent default changed as a result of this phase.
- Specialists run on the custom engine only; LangGraph-orchestrated specialists are a natural extension of the existing Phase 8 engine port but are not implemented in this phase.
- The synthesizer's aggregation policy is `best_effort` only; a `require_all` policy is modeled in the enum but not wired to any endpoint, since the phase's justified scope did not need it.
- The comparative evaluator measures one frozen local scenario per invocation; it is explicit evidence for the owner's own system-design defense, not a benchmark claim, and its `caveats` field says so on every persisted report.
- No dedicated web UI exists for multi-agent run creation or the comparison report, matching every prior phase's admin/inspection surfaces, which are also API/CLI-only; `apps/web` remains a minimal Phase 1 health shell.

## Git closeout

- Completion commit: created at Phase 12 closeout.
- Tag: `phase-12`, created on the exact completion commit.
- Remote verification: performed after push; commit and tag confirmed present on `origin`.
- Working tree: clean at closeout.

## Next phase

Phase 13 — Temporal, LangSmith observability, and cloud hardening, per `docs/phases/phase-13-temporal-observability-cloud-hardening.md`. Do not begin without explicit user authorization.
