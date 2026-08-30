# Phase 1 — Foundation, authentication, tenancy, and RBAC

## Scope

Create the pnpm/Turborepo monorepo with `apps/web`, `apps/api`, `apps/worker`, `packages/config`, and `packages/shared-types`; local PostgreSQL only (Redis may be configured but is not used for workflow execution); FastAPI/Next.js health and identity UI; migrations; OIDC validation; tenants/workspaces/memberships; RBAC/capabilities; CI quality gates. No workflow execution.

## Concepts being learned

Monorepo boundaries, browser/API authentication, JWT/OIDC validation, authentication vs authorization, multi-tenancy, RBAC plus capabilities, RLS defense in depth, migrations, dependency direction, contract generation.

## Architecture changes

Materialize web/API/worker deployables and backend layers. API constructs `ActorContext`; application policy and scoped repositories enforce access; PostgreSQL receives transaction-local tenant/actor context for RLS. Generate TypeScript client/types from OpenAPI rather than hand-maintaining Python/TS duplicates.

## Components/modules

Workspace tooling; validated settings; API app factory/error middleware/request correlation; identity adapter; tenant/workspace application services and repositories; policy decision service; SQL migrations; web login/session shell and workspace selector; worker health shell; test issuer/fake clock/ID fixtures.

## Data model changes

`tenants`, `workspaces`, `users`, `memberships`, optional `service_principals`, `security_audit_events`; UUIDv7, UTC, versions, composite ownership FKs, unique external issuer+subject and membership rules. Initial RLS policies and distinct runtime/migration roles.

## APIs and important interfaces

`GET /health/live`, `/health/ready`, `/v1/me`; tenant/workspace list/create/member-management endpoints as minimally required. `IdentityProvider.verify(token)`, `ActorContext`, `AuthorizationService.decide`, `ScopedRepository`. Mutations use idempotency keys and stable problem details from day one.

## Security requirements

Validate JWT algorithm, signature, issuer, audience, expiry/not-before; secure cookie/CSRF strategy at web boundary; deny-by-default route and repository checks; cross-tenant IDOR prevention; no tenant from body; safe audit logs; secret-free config; rate-limit auth/admin endpoints; migration role unavailable to runtime.

## Failure scenarios

Expired/forged/wrong-audience token, IdP/JWKS unavailability/cache rollover, deleted membership mid-session, duplicate tenant create, concurrent role update, RLS context leakage through pooled connection, database unavailable, stale OpenAPI client.

## Testing strategy

Unit policy matrix; JWT negative tests; API/repository/RLS cross-tenant integration tests; concurrent version update; idempotent command test; schema/migration up/down-on-empty validation; generated-client contract test; accessible UI smoke test; CI lint/type/unit/integration split.

## Acceptance criteria

One command starts minimal local dependencies and focused apps; authenticated user sees only authorized workspaces; ID substitution fails at service and RLS layers; roles/capabilities are auditable; web consumes generated contract; worker has no workflow logic; tests and security matrix pass; no secrets/private learning files tracked.

## Learning objectives

Trace identity from browser to row; implement/defend scoped authorization; explain RLS limits, CSRF vs CORS, token validation, service identities, and why UI hiding is not authorization.

## Coding exercises (private)

1. JWT claim validator with adversarial cases.
2. RBAC/capability decision table implementation.
3. Tenant-scoped repository written from scratch.
4. IDOR exploit test and repair.
5. Optimistic membership update race test.

## System-design knowledge expected

Choose external OIDC over custom auth; explain session/token boundary, tenant modeling alternatives, composite FKs/RLS, connection-pool context hazards, role vs capability tradeoffs, and future service-principal isolation.

## Zero-cost development and demo path

Run web, API, worker, and PostgreSQL locally; Docker may provide PostgreSQL and the deterministic OIDC test issuer. Hosted identity, managed databases, hosting, domains, billing credentials, and paid CI capacity are not required. The local issuer must exercise real JWT/JWKS validation, claims mapping, tenancy, RBAC, and RLS rather than bypassing authentication. Create the safe top-level `pnpm demo` skeleton for local startup/seed/health/identity inspection; it must be repeatable, force external integrations disabled, select only local adapters, and make no external calls. Local quality commands remain authoritative even if an optional hosted CI workflow is later enabled. A hosted-compatible OIDC adapter remains an unselected production seam.

## Explicitly deferred

Runs/tasks/state machines; queues and Redis execution; tools/models/approvals; full design system; concrete production IdP selection; billing; SCIM/SSO; API keys beyond minimal service-principal seam.
