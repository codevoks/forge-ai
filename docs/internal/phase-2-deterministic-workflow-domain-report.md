# Phase 2 — Deterministic workflow domain completion report

## Scope completed

Implemented the deterministic persisted workflow domain: immutable published workflow versions, run creation, objective snapshots, task DAG instantiation, dependency readiness, explicit run/task transitions, append-only execution events, tenant-scoped query APIs, and a dark charcoal/electric violet web demonstration surface.

## Product changes

- Added workflow/run domain state machines, transition validation, DAG validation, and dependency readiness evaluation.
- Added PostgreSQL tables for workflow templates, workflow versions, workflow steps, workflow edges, objectives, runs, tasks, task dependencies, task attempts, and execution events.
- Enforced tenant/workspace ownership, RLS access boundaries, runtime immutability for published workflow snapshots, and one active task attempt per task.
- Added `/v1/workflows` and `/v1/runs` API families plus a deterministic `advance` command that advances exactly one ready task at a time.
- Extended local seed/demo data with a deterministic incident-response workflow.
- Extended the web UI to show the published workflow, create a run, advance ready tasks, and inspect persisted task/event state.

## Security classification

| Area | Status | Evidence |
| --- | --- | --- |
| Tenant/workspace isolation | Protected and verified | Cross-tenant run access returns not found; RLS blocks run reads without scope. |
| Workflow publication authorization | Protected and verified | Viewer publish attempts are denied. |
| Run creation/advancement authorization | Protected and verified | Viewer run creation is denied; advancement requires the same workspace capability. |
| Immutable workflow snapshot | Protected and verified | Runtime role cannot mutate/delete published workflow versions/steps/edges. |
| Objective/input bounding | Protected and verified | API/domain enforce objective length and DAG size bounds. |
| Prompt/tool/MCP attack surfaces | Not applicable yet | No model, tool, retrieval, MCP, or external content execution exists in this phase. |
| Queue/worker replay abuse | Not applicable yet | Distributed queue/worker execution starts in a later phase. |

## Validation evidence

- `pnpm generate:types` — passed.
- `pnpm --filter @forge/api test` — 16 passed, 12 deselected.
- `pnpm --filter @forge/api test:security` — 12 passed, 16 deselected.
- `pnpm test` — passed across API, web, worker, config, and shared-types workspaces.
- `pnpm lint` — passed.
- `pnpm typecheck` — passed.
- `pnpm build` — passed with elevated local build permission after the sandbox-blocked Turbopack/PostCSS worker-port attempt.

## Zero-cost evidence

The phase uses local PostgreSQL, local web/API/worker processes, seeded deterministic workflow data, and external integrations forced to `disabled` by the demo script. No paid model provider, managed database, cloud queue, purchased domain, or billable SaaS integration is required for development, testing, or demonstration.

## Demonstration evidence

The local demo was exercised through the web UI at `http://127.0.0.1:3000`:

1. Alice Admin loaded with tenant/workspace capabilities.
2. The seeded `Incident Response Demo` workflow appeared as an immutable four-step DAG.
3. A deterministic run was created.
4. The run advanced one ready task per user action until all four tasks succeeded.
5. Persisted execution events showed ordered run/task transition history.
6. Bob Viewer demonstrated the authorization boundary by loading workflow visibility without the run-creation capability.

The API/state demonstration also verified idempotent command behavior and cross-tenant denial:

```text
first_create_status: 201
second_create_status: 201
same_run_replayed: True
key_reuse_different_payload_status: 409
key_reuse_different_payload_code: idempotency_key_reused
mallory_cross_tenant_get_status: 404
mallory_cross_tenant_get_code: run_not_found
```

## Intentional limitations

- No Redis queue, worker lease, retry/backoff, checkpoint recovery, cancellation command, LLM planning, tool execution, approvals, MCP, replay UI, or live-model evaluation exists yet.
- The deterministic `advance` command is a local execution adapter over the real persisted architecture, not the final distributed executor.
- Production SaaS session handling remains deferred; the local demo issuer remains development-only.

## Completion mapping

This report is paired with the exact completion commit tagged `phase-2` after final demonstration and remote verification.
