# Phase 6 — Human approval and AI security boundaries report

## Scope completed

Phase 6 implemented the human approval boundary for high-risk simulated effects:

- code-enforced `approval.decide` capability and seeded `Ava Approver`;
- committed `waiting_approval` task/attempt state;
- persistent `policy_versions`, `integration_connections`, `approval_requests`, and `approval_decisions`;
- exact-action binding hash over tenant, workspace, run, task, invocation, tool version, action hash, and canonical arguments;
- approval request listing, approval, rejection, and expiry APIs;
- `Idempotency-Key` and `If-Match` enforcement for decisions;
- separation-of-duty control that denies requester self-approval;
- worker suspension before adapter execution and resume through a new outbox message after approval;
- one-time approval consumption before the simulated effect executes;
- rejection and expiry fail-closed behavior;
- SSRF-ready URL policy primitive and fake secret-reference resolver;
- reusable adversarial URL corpus;
- web approval inbox controls in the established dark charcoal and electric violet design system;
- focused zero-cost `pnpm demo:approvals` evidence script.

Planner-created executable actions, notification delivery, real egress-capable tools, real secret managers, MCP approvals, and multi-agent approval chains remain deferred to their owning phases.

## Architecture notes

The implementation preserves the settled modular-monolith architecture. Human approval policy lives in `apps/api/src/forge_api/domain/approvals.py`, orchestration lives in `apps/api/src/forge_api/application/approval_service.py`, persistence lives in `apps/api/src/forge_api/infrastructure/approval_repositories.py`, and the worker integration lives in `apps/api/src/forge_api/application/tool_runtime.py`.

The most important implementation fix found during validation was transaction placement: approval suspension and expiry mutations must commit before the API/worker reports a controlled denial or wait state. Phase 6 now commits durable suspension/expiry state first, then returns the safe outcome. This prevents a worker from reporting `waiting_approval` while rolling back the approval row.

## Security classification

| Area | Classification | Evidence |
|---|---|---|
| Authentication and workspace authorization | Protected and verified | Existing JWT/RBAC tests plus `approval.decide` capability checks |
| Tenant/workspace isolation | Protected and verified | Approval RLS tests and outsider approval-list denial |
| Exact-action approval binding | Protected and verified | Mutated invocation arguments produce `approval_binding_mismatch` |
| Separation of duties | Protected and verified | Requester self-approval returns `approval_self_forbidden` |
| Viewer/outsider approval attempts | Protected and verified | Viewer returns `approval_decision_forbidden`; outsider sees no rows |
| Stale version and duplicate decision safety | Protected and verified | `If-Match` conflict and idempotent same-key replay tests |
| Expiry fail-closed behavior | Protected and verified | Expired approval returns `approval_expired` and fails run/task |
| Approval consumption before execution | Protected and verified | Completed approval transitions to `consumed` after worker execution |
| SSRF-ready network boundary | Protected and verified for current primitive | Adversarial URL corpus denies HTTP, loopback, metadata, and private IP targets |
| Secret leakage | Protected and verified for current primitive | Fake resolver returns only `[redacted]` material |
| Prompt injection through tool output | Protected and verified from prior phase; still regression-tested | Untrusted tool output remains labeled as evidence and does not become instruction |
| Planner-selected approvals | Not applicable yet | Plans are not executable in Phase 6 |
| Real external side effects | Not applicable yet | Only deterministic local simulated effects exist |

No genuine security blocker remains for Phase 6.

## Zero-cost evidence

Default settings require `FORGE_EXTERNAL_INTEGRATIONS=disabled` and `FORGE_MODEL_PROVIDER=fake`. Phase 6 uses local PostgreSQL, local Redis, local deterministic workers, a local approval UI/API, fake secret references, and deterministic local tool adapters. No model/provider/billable cloud call is required.

`pnpm demo:approvals` prints deterministic evidence for:

- `approval_requested`: task waits for approval before effect execution;
- `self_approval_denied`: requester cannot approve their own action;
- `approval_consumed_and_run_completed`: Ava approval resumes and the worker consumes approval once;
- `approval_rejection_failed_closed`: rejection fails the run safely;
- `approval_expiry_failed_closed`: expired approval fails closed;
- `network_and_secret_boundaries`: SSRF-ready URL denials and redacted secret reference;
- `phase6_zero_cost_summary`: `paid_provider_calls: 0`.

## Validation results

- `pnpm --filter @forge/api lint`: passed.
- `pnpm db:migrate`: passed.
- `pnpm db:seed`: passed.
- Focused functional regression: `7 passed, 25 deselected`.
- Focused security/adversarial regression: `25 passed, 1 deselected`.
- `pnpm --filter @forge/api test`: passed, 40 selected tests.
- `pnpm --filter @forge/api test:security`: passed, 29 selected security tests.
- `pnpm lint`: passed.
- `pnpm typecheck`: passed.
- `pnpm test`: passed across API, worker, web, config, and shared-types packages.
- `pnpm test:security`: passed across API, worker, web, config, and shared-types packages.
- `pnpm build`: passed after rerun with local elevated permissions because sandboxed Turbopack process creation was blocked.
- `node scripts/check-public-files.mjs`: passed.
- `pnpm demo:approvals`: passed.
- Browser demonstration: passed at `http://127.0.0.1:3000/`; showed approval wait, self-approval denial, Ava approval, consumed approval, succeeded tasks/run, invocation ledger, and evidence provenance.

## Product gate

Passed after implementation, full validation, live demonstration, documentation update, completion commit, remote push, and `phase-6` tag verification.

## Hiring-readiness learning gate

Not tested. Product implementation is complete, but owner mastery still requires reconstruction and interview-style explanation of exact-action approval, transaction boundaries, separation of duties, idempotency/version interactions, expiry/rejection fail-closed behavior, SSRF/secret primitives, and why model/tool output is never authoritative.

## Deferred items

- Notification delivery for approval requests.
- Real secret manager integration.
- Egress-capable tools that use the network policy in production adapters.
- Planner-selected executable actions.
- Approval UX beyond the local demo inbox.
- MCP approval boundaries.
- Multi-agent approval chains and delegated approval policy.
- Final integrated red-team audit across model, tool, approval, MCP, retrieval, and multi-agent chains.
