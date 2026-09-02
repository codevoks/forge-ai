# Final whole-project production-readiness and security audit

This is not a phase. It is the dedicated end-to-end audit AGENTS.md requires after all planned implementation phases (1-13) are complete: "Phase-level security validation does not replace the final integrated security/red-team audit... perform a dedicated end-to-end adversarial audit across the fully integrated system, including attack chains that cross multiple components." No new product capability was added; only correctness/security fixes and documentation/public-repository corrections.

## Scope

Reconstructed the implemented system from code (not documentation) across authentication, tenancy/RLS, the durable engine, typed tools, approvals, bounded agents, LangGraph/LangChain, evaluations, the debugger, MCP, multi-agent execution, budgets, OpenTelemetry, and the Phase 13 cloud-hardening artifacts. Ran the complete regression suite, performed chained/cross-boundary red-team attacks (not just re-running per-phase tests), audited the public repository and Git history, and produced one final integrated live demonstration through the actual browser.

## Genuine finding and fix: budget reservation orphaned by a worker crash

**How it was found:** while working through the audit's "budgets/resource abuse" checklist item "settlement/release correctness," tracing `ToolRuntime.invoke_for_claim`'s reserve-then-invoke-then-settle sequence against `WorkerRepository.run_recovery_scan` (the code path that reclaims a task after a worker crash) showed the recovery scan reclaimed the stale task attempt but never touched `budget_reservations`. A reservation made just before a crash stayed `reserved` forever, its usage stayed counted forever, and the inevitable retry reserved again for the same logical unit of work.

**Classification:** a resource-accounting drift, not an authorization bypass. It cannot be exploited to spend more than a workspace's budget ceiling allows — if anything it fails in the safe direction (throttling a workspace earlier than it should due to phantom usage). Classified `GENUINE BLOCKER` under the audit's own criteria (a real correctness gap `settlement/release correctness` explicitly asked about) and fixed before this report was written.

**Fix:** `WorkerRepository.run_recovery_scan` (`apps/api/src/forge_api/infrastructure/workflow_repositories.py`) now releases any `budget_reservations` row still `reserved` for a task whose stale attempt it just reclaimed, in the same transaction, and reverses the counted usage in `budget_usage_daily`. The scan's return value gained a `released_orphaned_reservations` count for operator visibility.

**Verification:** `tests/test_budgets.py::test_recovery_scan_reconciles_a_budget_reservation_orphaned_by_a_worker_crash` reproduces the exact crash scenario (claim a task with an already-expired lease, manually reserve budget the way `ToolRuntime` would, run the recovery scan, assert the reservation is released and usage is reversed) and passes. `pnpm demo:recovery` continues to pass with the new field visible in its output.

## Other red-team verification performed (no new findings)

- **Duplicate queue delivery vs. budget:** a new test (`test_duplicate_queue_delivery_never_double_reserves_budget`) redelivers every outbox message for a 3-tool-call run twice and confirms exactly 3 settled reservations, not 6 — `ToolRuntime`'s idempotent-reuse path (an already-`succeeded` invocation returns before any reservation) already prevented this; it was previously verified for invocation count but not budget count specifically.
- **Duplicate budget settlement:** a new test confirms settling the same reservation twice raises `ProblemError(409)` before any usage adjustment on the second call — `BudgetReservationRepository.settle`'s `WHERE status = 'reserved'` guard already prevented this.
- **Agent decision schema injection:** confirmed `AgentDecision`'s base `StrictModel` sets `extra="forbid"` — a model response cannot smuggle an unexpected field (e.g. a fabricated grant/approval override) past schema validation.
- **Recursive/runaway agent delegation:** confirmed `AgentDecisionType` has exactly four values (`tool_call`, `complete`, `fail`, `request_replan`) with no spawn/delegate primitive — structurally impossible, not merely policy-denied.
- **RBAC fail-closed, live:** `curl`'d a direct `POST /v1/runs` as the seeded `viewer` role against a running instance of the current code; received `403 run_create_forbidden`, matching the browser's refusal to even attempt the request for that role.
- **Trace-context injection surface:** `trace_context` in an outbox message payload is exclusively server-generated (`RunService.create`'s span, never client input); `WorkerConsumer.consume_once` additionally type-checks it (`isinstance(..., dict)`) before use. No external write path into `outbox_messages` exists. No forgery surface.

## Documented, non-blocking observability limitation — confirmed live, not just in tests

Live browser evidence (see LIVE DEMO in the closing chat report) directly confirmed the previously-documented Phase 13 limitation: a run's initial parallel ready tasks share the root OTel `trace_id` (confirmed identical `trace_id`/`correlation_id` across `run.created`, `run.running`, and both parallel specialists' `task.trace_correlated` events), while a task that becomes ready later via the ordinary completion path gets its own fresh, still-genuinely-real trace (confirmed via the local trace-export artifact showing distinct non-null `trace_id` values for the later `task.trace_correlated` events). Classified **IMPLEMENTED WITH KNOWN LIMITATION**, not a blocker: every event still carries genuine OTel instrumentation and a real correlation id; full causal traceability across the whole run already exists independently through the pre-existing `causation_id`/`sequence` event-ordering mechanism (unaffected by this limitation); and closing it fully (threading `trace_context` through `WorkerRepository.complete_attempt`'s internal `mark_newly_ready_tasks` call) is a natural, bounded follow-up, not a correctness or security gap.

## Public repository fix: stale README

The primary `README.md` had not been updated since an early state of the project — it described only "web, API, and worker health shells" and named none of the platform's actual capabilities (durable execution, typed tools, approvals, bounded agents, LangGraph, evaluations, debugger/replay, MCP, multi-agent, budgets, observability, cloud-hardening design). Rewritten to accurately describe what Forge does, its architecture (with a Mermaid diagram), local setup, the zero-cost demo path, and quality-check commands — all in professional English with no internal phase numbering, matching AGENTS.md's public-repository language rule.

## Environment constraints re-verified, not assumed

Disk space was re-checked at the start of this audit (as instructed, not assumed stale): approximately 350-400MB free, essentially unchanged from the Phase 13 closeout measurement. `terraform fmt -check` was re-run successfully (a fresh CLI download, no provider needed). `terraform init -backend=false`/`validate` and `docker build` were not re-attempted — the AWS provider plugin alone is 400MB+, and pulling Docker base images risked exhausting an already 97%+ full disk. These remain the documented outstanding verification steps in `docs/architecture/deployment-hardening.md`.

## Regression evidence

- `pnpm test`: 152 passed, 78 deselected. `pnpm test:security`: 78 passed, 152 deselected. (230 total: 3 new tests since the Phase 13 closeout commit, all in `test_budgets.py`.)
- `pnpm lint` / `pnpm typecheck` / `pnpm build` / `pnpm generate:types`: clean across all 5 packages.
- `pip-audit --skip-editable` / `pnpm audit`: zero known vulnerabilities (re-confirmed, unchanged from Phase 13 closeout).
- `pnpm capacity-report`: 60/60 runs completed, `paid_provider_calls: 0` (re-run, consistent with Phase 13's measured numbers).
- `pnpm backup-restore-drill`: passed, zero row-count mismatches (re-run).
- `node scripts/check-public-files.mjs` / `git diff --check`: passed.
- One genuine methodology issue caught and corrected mid-audit: leftover manually-started API/worker processes (started for live browser demonstration) were still running against the same local Postgres/Redis when the automated test suite was first re-run, causing 7 spurious test failures from cross-process contention — not a code regression. Stopping those processes and re-running produced a fully clean result, confirmed twice.

## Live demonstration

Performed through the actual browser (genuine `mcp__Claude_Browser__*` tooling, confirmed available and used, not simulated) against a freshly restarted API/worker/web stack running the exact audited code: identity switching (including a no-membership actor correctly seeing "No accessible workspaces"), a Multi-Agent Investigation Demo run created and driven to completion, a real exact-action approval clicked through the UI as Ava, live inspection of the bounded-agent iteration ledger and evidence provenance (including the seeded prompt-injection test strings, correctly labeled `untrusted_tool_output` and inert), the execution debugger and a local trace-export artifact directly confirming both the OTel implementation and its documented propagation limitation, and a fail-closed RBAC denial (viewer role, both in the UI and via a direct API call). Full detail in the closing chat report's LIVE DEMO section.

## Recruiter/CV material

Produced in the closing chat report only, per the audit instruction not to add recruiter/CV material to the repository.

## Closeout

One audit-fix commit on `main` (recovery-scan budget reconciliation fix, new tests, README rewrite, security-threat-model and status updates, this report). No new phase, no moved tags. `phase-1` through `phase-13` remain exactly where they were.
