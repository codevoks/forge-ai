# Phase 13 — Temporal decision, observability, budgets, and cloud hardening report

This internal report preserves Phase 13 completion evidence without exposing phase history in the product UI or primary README.

## Scope completed

- **Temporal decision (Q-005, evidence-backed no-adoption comparison, not a live spike):** rejected adoption. Forge's existing Postgres-authoritative durable engine (task/attempt state with fencing tokens, transactional outbox, `RetryPolicy`, cancellation cascade, dead-letter requeue, recovery scan) already provides the guarantees Temporal's workflow-history/replay model exists to provide, without a determinism/replay-safety constraint on application code and without a second stateful service. A new local load/soak drill (`pnpm capacity-report`) measured real single-machine throughput (~5 runs/sec, ~20 tasks/sec, p50 5.3s / p95 7.1s, unpooled local Postgres) showing no workflow-history-shaped bottleneck. Full reasoning and evidence in `docs/architecture/decisions.md` Q-005.
- **OpenTelemetry instrumentation, genuinely wired end-to-end:** `ports/telemetry.py::TelemetryPort` and `infrastructure/telemetry.py::ForgeTelemetry` (local JSONL span exporter as the always-on zero-cost default; an OTLP exporter — usable by any OTLP collector including self-hosted Langfuse or local Jaeger — attaches only when explicitly enabled). `RunService.create` opens a root `run.create` span and threads its real W3C `traceparent` through `RunRepository.create_run` into the outbox payload for a run's initial ready tasks; `WorkerConsumer.consume_once` extracts that context, continues it in a `task.execute` span, and records a `task.trace_correlated` execution event whose `correlation_id` is the real OTel trace id (not a fresh random id per event, closing a real gap `EventRepository.append` had since Phase 3). `EventRepository.append` gained optional `trace_context`/`correlation_id` parameters, defaulting to prior exact behavior for every existing call site.
- **Phase 10 trace-export extended with real correlation:** `create_trace_export`'s `event_refs` now include the real `trace_id`/`correlation_id` per event; the exporter enum gained `"langfuse"` alongside `"local"`/`"langsmith"`, gated by the same explicit-opt-in/fail-closed pattern the LangSmith path already used.
- **Hierarchical budgets:** `domain/budgets.py`, `infrastructure/budget_repositories.py` (atomic conditional-`UPDATE` reservation — verified under real concurrency, not just reasoned about), `application/budget_service.py` (reserve/settle/release), wired into `ToolRuntime.invoke_for_claim` around every tool call. A new read-only `GET /v1/budgets/usage` endpoint. Default policy caps `max_currency_minor_per_day` at zero.
- **CI/dependency hardening, with two real security findings closed:** all GitHub Actions pinned to commit SHAs; a new `secret-scan` job (gitleaks, full git history); `pip-audit`/`pnpm audit` steps added to CI. Running them locally surfaced 31 real Python vulnerabilities (cryptography, pyjwt, pytest, python-multipart, setuptools, starlette) and 39 real JS vulnerabilities (next, postcss, vitest, turbo) in the pre-existing dependency pins — every one closed with a minimum-safe-version upgrade, verified by a full green regression run after each round.
- **Local Terraform (authored and formatted, not appliable, not fully validated — see Limitations):** `infra/terraform/` — VPC with public/private subnets across AZs, NAT gateways, least-privilege security groups; RDS Postgres (encrypted, private, no public access, automated backups); ElastiCache Redis (encrypted); ECS Fargate services for API/worker behind an ALB with TLS 1.2+ and an HTTP→HTTPS redirect; least-privilege IAM (execution role scoped to exactly the secrets/keys this config creates, no wildcard); Secrets Manager for DB credentials; no remote backend (zero-cost path needs no pre-existing S3/DynamoDB state store).
- **Container hardening:** multi-stage, non-root (`10001:10001`), minimal-base Dockerfiles for `apps/api`, `apps/worker`, `apps/web` (Next.js `standalone` output).
- **Backup/restore drill:** `pnpm backup-restore-drill` — real `pg_dump`/`pg_restore` cycle into a throwaway database inside the local Postgres container, row-count-verified, self-cleaning; run twice successfully (~0.2-0.3s backup, ~1.9s restore).
- **Load/soak drill and capacity report:** `pnpm capacity-report` — see above; feeds both the Temporal ADR and `docs/architecture/scale-observability-cost.md`'s new measured-evidence section.
- Fixed a real, pre-existing gap found while working: root `package.json` was missing the `demo:recovery` script that `apps/api/package.json` already defined.
- 19 new automated tests (`test_budgets.py`: 11, `test_telemetry.py`: 6, plus 2 extending `test_debugging.py`/`test_reliability.py`), with zero regressions to the existing 208 Phase 1-12 tests (227 total: 149 non-security + 78 security).

## Architecture changes

- `ports/telemetry.py` / `infrastructure/telemetry.py`: `TelemetryPort` Protocol, `ForgeTelemetry` (real OTel `TracerProvider`, local JSONL exporter with `sanitize_payload` redaction, optional gated OTLP exporter), `NullTelemetry` (safe default for every pre-Phase-13 `WorkerConsumer`/`RunService` call site — no existing construction call had to change). `SimpleSpanProcessor` already isolates exporter failures from the wrapped business operation (verified by `test_exporter_failure_never_blocks_the_wrapped_operation`), so telemetry can never fail a run/task.
- `workflow_repositories.py`: `EventRepository.append` gained optional `trace_context`/`correlation_id`; `correlation_id_from_trace_context()` reformats an OTel 128-bit trace id as a UUID string for storage in `execution_events.correlation_id` (the schema column was already `uuid not null` since Phase 3 — this is the first code path to populate it meaningfully instead of a fresh random id every time). `add_task_execution_requested`/`mark_newly_ready_tasks`/`create_run`/`_start_run` gained optional `trace_context` threading, defaulting to prior behavior everywhere except the one instrumented call site (`RunService.create`'s span wraps `create_run`).
- `domain/budgets.py` / `infrastructure/budget_repositories.py` / `application/budget_service.py`: `BudgetEstimate`, `BudgetScope`, `ReservationStatus`; `BudgetUsageRepository.try_reserve` is a single conditional `UPDATE ... WHERE requests_used + %s <= max_requests ... RETURNING id` — atomic under concurrency by construction. Reserve happens before a tool adapter is invoked; settle happens after (including on the `outcome_unknown` path, since work may genuinely have happened); release happens only on a definite `ProblemError` failure before any adapter call took effect.
- Migration `013_temporal_observability_cloud_hardening.sql`: `budget_policies`/`budget_usage_daily`/`budget_reservations` with RLS. No Temporal linkage table — the evidence-backed comparison rejected adoption, so there is no workflow-history reconciliation state to persist. No shared-constraint widening (learned from Phase 12's migration-replay hazard) — this migration only adds new tables.
- `debugging.py` / `debugging_service.py` / `debugging_repositories.py`: the trace-export `exporter` Literal widened to include `"langfuse"`; `create_trace_export`'s `event_refs` now carry real `trace_id`/`correlation_id` per event via a new `_trace_id_from_context` helper.

## Two genuine bugs found and fixed during implementation

1. `budget_policies_worker` RLS policy was initially written `for select` only, on the assumption that budget policies are always admin-authored. This broke immediately: `BudgetService.reserve`'s auto-provisioning (`get_or_create_workspace_policy`) runs inside `ToolRuntime`'s worker-only transaction (no `tenant_id` set), so the first real tool call in the test suite failed with `InsufficientPrivilege`. Fixed by making the policy apply to all commands, matching the established `tool_invocations_worker`/`budget_usage_daily_worker` pattern.
2. `apps/api/src/forge_api/scripts/seed.py` didn't delete the three new budget tables before `tasks`/`runs`, so the second `pnpm db:seed` after any tool-invoking test run failed on the `budget_reservations` foreign key to `tasks`/`runs` (`on delete restrict`). Fixed by adding the three deletes in dependency order, matching every prior phase's pattern of extending the seed reset list for new tables.

## Security classification

| Area | Classification | Evidence |
| --- | --- | --- |
| Budget reservation race/leak | Protected and verified | `try_reserve`'s atomic conditional `UPDATE`; a 20-thread race test against a ceiling of 5 confirms exactly 5 succeed |
| Budget tenant isolation and worker-write boundary | Protected and verified | RLS-scoped tables; a write with neither tenant nor worker transaction context is rejected |
| Budget fail-closed enforcement | Protected and verified | Exceeding the ceiling raises `ProblemError(429, "budget_exceeded")` before the adapter is invoked |
| Budget default-zero monetary ceiling | Protected and verified | Auto-provisioned policies cap `max_currency_minor_per_day` at zero |
| Telemetry secret/credential leakage | Protected and verified | Span attributes pass through `sanitize_payload`; a secret-named key is redacted in the local exporter |
| Telemetry exporter-failure isolation | Protected and verified | An unwritable export path drill confirms the wrapped operation still completes |
| Telemetry live-export fail-closed default | Protected and verified | OTLP attaches only when export mode, external integrations, and an endpoint are all explicitly set |
| Telemetry framework non-authority | Protected and verified | `task.trace_correlated` is `authoritative_for_projection=False`; trace context never affects scheduling |
| Temporal decision authority | Not applicable — no adoption | No external workflow-history service exists in this architecture |
| CI dependency/secret supply chain | Protected and verified | `pip-audit`/`pnpm audit` in CI; gitleaks secret-scan job; all actions pinned to commit SHAs |

Full detail in `docs/architecture/security-threat-model.md`'s classification table.

## Zero-cost evidence

- Default `external_integrations` remains `disabled`; `telemetry_export_mode`/`langsmith_export_mode` both reject `enabled` in `assert_zero_cost_safe()`.
- The OTLP telemetry exporter and live LangSmith/Langfuse trace export are opt-in and blocked by default; no network call is attempted unless explicitly configured.
- `pnpm capacity-report` and `pnpm backup-restore-drill` report `paid_provider_calls: 0` and touch only the local Docker Compose stack.
- Terraform is authored/formatted only; no `apply`/`plan` against real AWS was run or is reachable from any default command.

## Validation evidence

- `pnpm --filter @forge/api db:migrate` — migration `013` applied cleanly; replay safety verified (migrate → seed → migrate → seed → migrate all succeeded in sequence).
- `pnpm test` — 149 passed, 78 deselected (security-marked).
- `pnpm test:security` — 78 passed, 149 deselected.
- `pnpm lint` / `pnpm typecheck` / `pnpm build` — clean across all 5 workspace packages (mypy strict: 103 API source files, 0 issues).
- `pnpm generate:types` — OpenAPI export includes the new `/v1/budgets/usage` route; shared TypeScript types regenerated.
- `pip-audit --skip-editable` / `pnpm audit` — zero known vulnerabilities (down from 31 and 39 respectively, closed during this phase).
- `node scripts/check-public-files.mjs` — passed.
- `git diff --check` (staged) — passed, no whitespace issues.
- `terraform fmt -check` — passed. `terraform validate` could not run in this environment (insufficient local disk space to download the AWS provider plugin; see Limitations). Manual resource-by-resource review performed instead.
- `docker build` was not attempted for the three new Dockerfiles, for the same disk-space reason; manual review performed instead.

## Demonstration evidence

`pnpm capacity-report` (abridged): 60/60 runs completed, run creation 8.4 runs/sec, end-to-end throughput 5.0 runs/sec, estimated task throughput 20.2 tasks/sec, run latency p50 5.3s / p95 7.1s / p99 7.2s, `paid_provider_calls: 0`.

`pnpm backup-restore-drill` (abridged, two runs): backup 0.32s / 0.23s, restore 1.94s / 1.88s, zero row-count mismatches across `tenants`/`workspaces`/`users`/`runs`/`tasks`/`execution_events`, throwaway database dropped after each run, `paid_provider_calls: 0`.

`tests/test_telemetry.py::test_run_create_and_worker_task_share_one_trace_across_the_async_path` (live evidence, not just an assertion): creates a real run through the HTTP API, drives it to completion through a real worker with `ForgeTelemetry` wired, then confirms the two parallel root tasks' `task.trace_correlated` events share the exact same OTel trace id as the API's `run.create` span recorded in the local JSONL exporter — genuine cross-process trace correlation, not a mock.

`tests/test_budgets.py::test_real_tool_run_reserves_and_settles_budget_for_every_tool_call`: drives a real 3-tool-call run to completion and confirms all three `budget_reservations` rows reach `status='settled'` with the correct per-tool `operation` labels.

Final summary: `paid_provider_calls: 0` across every Phase 13 demonstration.

## Reproduction steps

```bash
pnpm install
pnpm db:up
pnpm db:migrate
pnpm capacity-report
pnpm backup-restore-drill
```

To inspect the underlying tests directly:

```bash
pnpm --filter @forge/api test -- tests/test_budgets.py tests/test_telemetry.py
pnpm --filter @forge/api test:security -- tests/test_budgets.py
```

## Limitations

- **Terraform `validate` and `docker build` were not executed** in this environment: the development machine had approximately 500MB of free disk space, insufficient for the ~400MB `hashicorp/aws` provider plugin or for pulling `python:3.11-slim`/`node:22.12.0-slim` base images without risking exhausting the disk entirely. This is a local disk-space constraint, not a network, credentials, or AWS-access problem — `terraform init -backend=false` did reach the public registry and installed the smaller `hashicorp/random` provider before failing. `terraform fmt` did run and passed. Both files were reviewed manually instead; re-running `terraform validate` and `docker build` once disk space is available is the outstanding verification step (see `docs/architecture/deployment-hardening.md`).
- **OTel trace propagation is bounded to a run's initial ready tasks**, not the full DAG: a task that becomes ready later via the ordinary completion path (not the run-creation path) gets its own fresh per-attempt trace rather than continuing the root trace. Every attempt still gets a real, correlatable OTel span — this only affects which spans share a `trace_id`, not whether tracing exists. Extending propagation through `WorkerRepository.complete_attempt`'s internal `mark_newly_ready_tasks` call is a natural next step, deliberately deferred to bound this phase's diff.
- **`apps/worker`'s packaging gap is pre-existing, not introduced or fixed here**: `forge_worker.main` imports `forge_api` directly without declaring it as a dependency in `apps/worker/pyproject.toml`. The new `apps/worker/Dockerfile` documents and works around this the same way local dev does (installing both packages into one environment) rather than fixing the underlying packaging.
- **No live LangSmith/Langfuse/OTLP export was validated**: no credentials or endpoint were approved for this session, so the live paths remain implemented-but-unexercised, correctly reported as `blocked`/fail-closed by their own status fields.
- **The comparative Temporal decision is a written, evidence-backed comparison**, not a live Temporal spike — the phase spec explicitly sanctions this as an equally valid zero-cost path. No Temporal server was installed or run.
- **The load/soak drill is a single-machine measurement** with no connection pool, explicitly not a production capacity claim; its 100x extrapolation is labeled unvalidated in its own output.
- No dedicated web UI exists for budget/telemetry inspection, matching every prior phase's admin/inspection surfaces (API/CLI-only); `apps/web` remains a minimal Phase 1 health shell.

## Git closeout

- Completion commit: created at Phase 13 closeout.
- Tag: `phase-13`, created on the exact completion commit.
- Remote verification: performed after push; commit and tag confirmed present on `origin`.
- Working tree: clean at closeout.

## Next phase

None scheduled. Phase 13 completes the planned phase sequence in `docs/phases/`. Any further work (the separate final whole-project production-readiness/red-team/freeze audit, or a new phase) requires explicit user authorization and is out of this phase's scope.
