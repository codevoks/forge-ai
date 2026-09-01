# Phase 10 — Execution history, debugger, safe replay, and trace export report

This internal report preserves Phase 10 completion evidence without exposing phase history in the product UI or primary README.

## Scope completed

- Added durable execution-history metadata on `execution_events`, including schema version, payload hash, trace context, sanitized diff, and retention class.
- Added tenant-scoped debugger persistence for projection verifications, replay sessions, replay artifacts, and trace-export artifacts.
- Added a debugger API surface for execution-history inspection, cursor-based event feeds, projection verification, safe replay, and local trace export.
- Added UI support for inspecting completed executions, causal event timelines, model/tool/agent evidence, Forge checkpoints, LangGraph checkpoint mirrors, projection status, replay artifacts, and trace-export artifacts.
- Added a deterministic zero-cost `pnpm demo:debugger` demonstration path.
- Added security/adversarial coverage for cross-tenant debugger access, forged cursors, viewer replay authorization, unsafe effect replay, live trace export fail-closed behavior, and replay tripwires.
- Preserved the Phase 9 LangChain/LangGraph/LangSmith boundaries: framework evidence is inspectable and correlatable, but never authoritative for Forge state, authorization, policy, or side effects.

## Architecture changes

Phase 10 introduced these implementation-grade contracts:

- `DebugEventSchema` and an event catalog for known execution events.
- `DebuggerRepository` for tenant-scoped history reads, debugger snapshots, projection verification persistence, replay-session persistence, replay-artifact persistence, and trace-export persistence.
- `DebuggingService` as the application boundary that enforces `run.read` and `run.recover`, idempotency, actor/workspace scope, and fail-closed external export behavior.
- Cursor encoding/decoding that binds cursors to the run and sequence boundary; forged or cross-run cursors are rejected.
- Projection verification that folds historical events into an expected run/task projection and compares it to current authoritative database state without mutating runtime state.
- Simulation replay that reconstructs observations and writes replay artifacts with tripwires proving no authoritative state mutation, approval reuse, real effect adapter call, or paid-provider call occurred.
- Effect replay mode that is intentionally blocked by default and does not reuse old approvals.
- Local trace export that correlates events, model calls, tool invocations, evidence, Forge checkpoints, agent iterations, and LangGraph checkpoint mirrors into a sanitized local artifact.

## Security classification

| Area | Classification | Evidence |
| --- | --- | --- |
| Debugger history tenant isolation | Protected and verified | Cross-tenant debugger reads return not found; event history is resolved through actor/workspace scope |
| Debug cursor tampering | Protected and verified | Forged cursor input is rejected with `debug_cursor_invalid` |
| Replay authorization | Protected and verified | Viewer identity can inspect allowed history but cannot create replay artifacts |
| Historical-state authority confusion | Protected and verified | Projection verification records findings only and never mutates authoritative run/task state |
| Unsafe side-effect replay | Protected and verified | `effect_replay` returns `blocked`; replay artifacts record no real effect adapter call |
| Approval reuse during replay | Protected and verified | Replay policy records `reuses_approval=false`; effect replay artifact tripwire records `approval_reused=false` |
| Idempotency/replay safety | Protected and verified | Replay and trace-export creation use idempotency records; repeated matching requests return stable artifacts |
| Payload and secret exposure | Protected and verified | Debugger UI/API expose sanitized payloads; secret-like fields remain redacted |
| Framework checkpoint authority | Protected and verified | LangGraph checkpoint mirrors are inspectable evidence only and are not used as authorization or runtime state authority |
| Live LangSmith/export path | Protected and verified for default profile | Local artifact mode records `live_export=false`; enabled mode fails closed while external integrations are disabled |
| Long-term immutable audit storage | Implemented but needing deeper final validation | Payload hashes are recorded, but WORM storage/cold archive is deferred |

## Zero-cost evidence

- Default external integration mode remains `disabled`.
- Default model/provider path remains deterministic fake execution.
- `pnpm demo:debugger` reports `paid_provider_calls: 0`.
- Simulation replay records `authoritative_state_mutated: false`.
- Local trace export records `live_export: false`.
- Live LangSmith/export mode fails closed unless external integrations are explicitly enabled.

## Validation evidence

Recorded during Phase 10 closeout:

- `pnpm db:migrate` — passed on isolated local PostgreSQL database `forge_phase10_559dd4ce`.
- `pnpm db:seed` — passed with debugger tables included in deterministic cleanup.
- `.venv/bin/pytest apps/api/tests/test_debugging.py -q` — `11 passed`.
- `pnpm demo:debugger` — passed; printed completed LangGraph execution, event timeline, projection verification `passed`, simulation replay `passed`, effect replay `blocked`, local trace export `local_artifact`, live LangSmith/export fail-closed behavior, cross-tenant denial, and `paid_provider_calls: 0`.
- `pnpm generate:types` — passed and regenerated OpenAPI-derived shared TypeScript types.
- `pnpm --filter @forge/api lint` — passed.
- `pnpm --filter @forge/web lint` — passed.
- `pnpm --filter @forge/web typecheck` — passed.
- `pnpm test` — passed: API `53 passed, 46 deselected`; web `1 passed`; worker `1 passed`; package checks completed.
- `pnpm test:security` — passed: API `46 passed, 53 deselected`; web `1 passed`; package checks completed.
- `pnpm lint` — passed across workspace packages.
- `pnpm typecheck` — passed across workspace packages.
- `pnpm build` — passed after rerunning outside the restricted sandbox because Turbopack process binding was blocked by local sandbox policy.
- `node scripts/check-public-files.mjs` — passed.
- `git diff --check` — passed.

## Demonstration evidence

The Phase 10 user-visible demo showed the actual UI at `http://127.0.0.1:3000/`:

- Alice Admin authenticated through the local OIDC/JWKS path.
- A completed `langgraph` run was visible with `Status: succeeded`.
- The LangGraph checkpoint mirror showed 18 tenant-scoped checkpoint records with framework state marked inspectable but non-authoritative.
- The Execution Debugger panel loaded 8 causal timeline events with schema version and payload-hash metadata.
- Projection verification showed `passed` with expected and actual run/task states matching.
- Simulation replay showed a replay artifact with `authoritative_state_mutated=false`, `real_effect_adapter_called=false`, `approval_reused=false`, and `paid_provider_calls=0`.
- Unsafe `effect_replay` showed `blocked` with `effect_replay_disabled`.
- Local trace export showed `local_artifact`, correlating events, model calls, tool invocations, and LangGraph checkpoints without live telemetry.
- The UI security posture showed raw payloads not exposed, effect replay disabled, framework state non-authoritative, and secrets redacted.

## Deferred items

- Server-sent events remain deferred; the cursor-based event feed is the baseline contract for a future SSE stream.
- Real effect replay remains intentionally disabled until a later explicitly approved design provides exact-action approval, current-policy checks, idempotency guarantees, and adapter-specific safety gates.
- Account-backed LangSmith export remains optional and unverified until explicitly approved.
- WORM/cold archival storage, compliance retention tiers, and tamper-evident external storage remain deferred.
- Replay of arbitrary side-effecting tools remains out of scope for this phase.
- Final integrated red-team audit remains required after all implementation phases.

## Git closeout

- Completion commit: commit tagged `phase-10`.
- Tag: `phase-10`.
- Remote verification: required at phase closeout.
- Working tree: clean verification required at phase closeout.
