# Phase 1 — Foundation, authentication, tenancy, and RBAC completion report

## Status

- Product gate: passed.
- Hiring-readiness learning gate: not tested. Product implementation can advance, but owner mastery is not inferred.
- Completion tag: `phase-1`, to be created only after final validation, demonstration, and a clean completion commit.

## Delivered scope

- Materialized the modular monolith foundation with `apps/web`, `apps/api`, `apps/worker`, `packages/config`, and `packages/shared-types`.
- Added local PostgreSQL through Docker Compose as the authoritative database.
- Added a FastAPI API with health, development OIDC token issuance, authenticated identity, workspace listing, workspace detail, and idempotent tenant/workspace creation.
- Added a Next.js web shell that exercises the real API identity, tenancy, RBAC, and capability contract using seeded local actors.
- Added a worker health shell with workflow execution explicitly deferred.
- Added generated OpenAPI-to-TypeScript contract artifacts for the web/shared type boundary.
- Added a safe `pnpm demo` command that starts local services with external integrations disabled.
- Added CI quality gates that use only local/open-source infrastructure and disabled external integrations.

## Security classification

| Area | Classification | Evidence target |
| --- | --- | --- |
| JWT algorithm/signature/issuer/audience/expiry validation | protected and verified | security tests |
| Tenant/workspace isolation and cross-tenant IDOR | protected and verified | service tests plus PostgreSQL RLS tests |
| RBAC/capability checks | protected and verified | policy tests and identity API output |
| Idempotency key reuse/conflict handling | protected and verified | API tests |
| Rate limiting on local auth/admin-like endpoints | protected and verified | security tests |
| Runtime/migration database role separation | protected and verified | migration and RLS tests |
| Secure production browser session, CSRF hardening, hosted IdP selection | implemented as architecture seam but needing deeper final validation | deferred production adapter decision |
| Distributed rate limiting | implemented locally but needing deeper final validation | deferred until multi-process/Redis phase |
| Tool-call authorization, prompt injection, MCP, approval bypass, agent runaway, checkpoint tampering | not applicable yet | no tool/agent/workflow surface exists in Phase 1 |
| Genuine security blocker | none after final validation passes | phase gate |

## Zero-cost verification

- Default local development and demo use Docker PostgreSQL, local API/web/worker processes, and the deterministic local OIDC issuer.
- `FORGE_EXTERNAL_INTEGRATIONS=disabled` is forced by `pnpm demo`.
- No paid model, hosted identity provider, managed database, cloud deployment, purchased domain, Temporal Cloud, Bedrock, AWS, or paid observability dependency is required.
- Potentially billable production integrations remain architectural seams only and are not exercised by default commands, tests, CI, or demo.

## Validation evidence

- `pnpm db:up`: passed; local Docker PostgreSQL container running.
- `pnpm db:migrate`: passed; Phase 1 schema, RLS policies, and runtime role grants applied.
- `pnpm db:seed`: passed; deterministic Alice Admin, Bob Viewer, and Mallory Outsider scenario seeded.
- `pnpm generate:types`: passed; OpenAPI contract exported and TypeScript types generated.
- `pnpm lint`: passed across API, web, worker, config, and shared-types. Next.js emitted a non-blocking `baseline-browser-mapping` freshness warning.
- `pnpm typecheck`: passed across API, web, worker, config, and shared-types.
- `pnpm build`: passed across API, web, worker, config, and shared-types. Next.js emitted a non-blocking `baseline-browser-mapping` freshness warning.
- `pnpm test`: passed. API: 8 passed, 7 deselected. Worker: 1 passed. Web: 1 passed. Config/shared-types Node test packages contained no tests yet.
- `pnpm test:security`: passed. API security/adversarial suite: 7 passed, 8 deselected. Web security suite: 1 passed. Worker security task compiled the worker shell.
- `node scripts/check-public-files.mjs`: passed after Git initialization and local excludes; private runtime artifacts are not visible to Git.

## Demonstration evidence

- `pnpm demo` started local PostgreSQL, applied migrations, seeded demo data, and started API, web, and worker with `FORGE_EXTERNAL_INTEGRATIONS=disabled`.
- Browser UI demonstration opened `http://127.0.0.1:3000`.
- Alice Admin view showed `Security Demo Workspace` with `tenant_admin` role and capabilities: `member.manage`, `run.create`, `run.read`, `tenant.admin`, `workspace.admin`, and `workspace.read`.
- Bob Viewer view showed the same workspace with `viewer` role and capabilities: `run.read` and `workspace.read`.
- Mallory Outsider view showed no accessible workspaces.
- Backend live check showed Mallory reading Alice's workspace is denied with HTTP `403` and problem code `workspace_forbidden`.
- Backend live check showed repeated tenant creation with the same `Idempotency-Key` returns HTTP `201` for both attempts and the same semantic response.
- After the backend demo, `pnpm db:seed` was run again so the UI remains in the clean bounded demo state for inspection.

## Deferred items

- Workflow execution, queues, outbox, retries, checkpoints, and recovery.
- Redis-backed coordination.
- Tools, model providers, MCP, agents, prompt-injection defenses, and human approval flows.
- Production IdP/provider selection and production deployment.
- Full design system and product UX beyond the Phase 1 identity/tenancy shell.

## Phase history mapping

- Completion report: `docs/internal/phase-1-foundation-authentication-tenancy-rbac-report.md`
- Completion commit: the local commit tagged `phase-1`; remote verification is pending GitHub authentication repair.
- Completion tag: `phase-1` locally; remote tag push is pending GitHub authentication repair.
