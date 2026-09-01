# Phase 13 — Temporal decision, LangSmith observability, budgets, cloud, and hardening

## Scope

Complete production-path hardening: local/self-hosted Temporal evidence spike/decision and bounded integration if justified; full OTel and optional LangSmith/Langfuse adapters; hierarchical rate/token/currency/time budgets; Docker/CI security; reviewable AWS/Terraform deployment design without mandatory provisioning; backups/recovery, load/soak/failure tests, runbooks, SLOs, retention, dependency/supply-chain controls, and final architecture/learning reconstruction.

## Concepts being learned

Durable execution framework tradeoffs, workflow determinism/signals/history, telemetry and SLOs, capacity planning, admission/fairness, FinOps, IaC/cloud security, backup/restore, deployments, incident response, senior architecture defense.

## Architecture changes

Run a free local/self-hosted Temporal spike against representative long-lived/approval/retry/cancel workflows through `WorkflowEngine`; write adopt/reject ADR. If adopted, Temporal orchestrates while PostgreSQL remains product/audit authority and Forge policy/tools remain boundaries; define consistency/reconciliation and migration. Add a production deployment/observability/resource topology based on measured local tests, clearly separating verified local behavior from unprovisioned cloud design.

## Components/modules

Temporal spike/adapter/workflows/activities if accepted; OTel instrumentation/export/config and optional LangSmith/Langfuse adapters; budget reservation/settlement/rate tables; tenant admission/fairness; non-applying Terraform modules and validation; Docker images; CI/CD/security scanning; backup/restore and incident runbooks; load generator and capacity report.

## Data model changes

Budget policies/reservations/usage ledger/rate-card versions; telemetry sampling/export metadata; retention/archive state; Temporal workflow linkage/reconciliation records only if adopted. The zero-cost path uses no remote Terraform backend and no required LangSmith account; any production state backend or telemetry destination is configured only during a separately approved deployment and never stored in the application database.

## APIs and important interfaces

Budget/admin usage and operational health endpoints with strict capabilities; stable `WorkflowEngine`, `BudgetService`, `TelemetryPort`, `SecretResolver`. Optional infrastructure outputs feed deployment configuration through secret references, not committed values; no default command provisions managed services.

## Security requirements

Private networking, TLS, least-privilege IAM/workload identities, managed secrets/KMS, egress controls, encrypted backups, WAF/rate limits as applicable, container non-root/read-only/minimal images, pinned CI actions/images, dependency/image/IaC scanning, audit access/retention, incident kill switches, no production data in tests/evals.

## Failure scenarios

Region/AZ/service/provider outage; DB failover/restore; Redis flush; Temporal unavailable/history/version incompatibility; deploy rollback/migration skew; telemetry/cardinality explosion; budget reservation leak/race; autoscaling storm; queue/database saturation; secret rotation; compromised integration; backup corruption.

## Testing strategy

Temporal parity/failure/operational benchmark and decision matrix on the local/self-hosted path; instrumentation/redaction/exporter-outage tests; atomic budget concurrency/reconciliation; representative local load/soak and 100x modeled capacity; local chaos/failover drills; backup restore proving local-profile RPO/RTO; IaC format/validate/non-applying plan/policy/security scans; documented canary/rollback procedure; full deterministic and frozen behavioral regressions.

## Acceptance criteria

Temporal ADR contains a measured local adopt/reject decision; traces link the full async path without secrets; LangSmith integration is implemented as an opt-in adapter with redaction, exporter-failure tests, local fallback evidence, and live/self-hosted execution evidence only if explicitly approved; budgets fail closed and reconcile; local capacity limits/bottlenecks and modeled production cost are clearly distinguished; least-privilege AWS/Terraform topology validates without requiring deployment; restore/incident drills meet or revise local-profile targets honestly; the final zero-cost demo and architecture review pass. No managed-cloud behavior is claimed without separately approved evidence.

## Learning objectives

Evaluate/adopt/reject Temporal from evidence; instrument and operate the platform; place LangSmith as observability/evaluation tooling rather than authority; perform capacity/cost/IaC/security reasoning; lead incident and architecture reviews; rebuild a simplified Forge independently.

## Coding exercises (private)

1. Minimal Temporal workflow/activity with retry/signal/cancel, or equivalent comparison if rejected.
2. OTel/LangSmith async trace propagation and redaction.
3. Atomic hierarchical budget reservation race.
4. Capacity/backpressure calculation from load results.
5. Terraform least-privilege review/fix.
6. Final reconstruction: simplified durable Forge without production source.

## System-design knowledge expected

Defend Temporal decision and migration semantics; SLO/alert/capacity math; database/queue/provider bottlenecks; budget consistency; AWS topology/IAM/network/backup; rollout/rollback; multi-region deferral; complete threat/failure model under interviewer challenge.

## Zero-cost development and demo path

Run any Temporal spike with a free local/self-hosted server, or produce an evidence-backed no-adoption comparison; Temporal Cloud is never required. Use local OpenTelemetry collection and a free local viewer, with optional LangSmith/Langfuse execution only if its learning value justifies the resource cost and the owner explicitly approves credentials or an endpoint. Run load, soak, backup/restore, failure, and budget tests on the bounded local profile and label their hardware limits. Author, format, validate, scan, and where safe produce non-applying Terraform plans, but do not provision AWS, Bedrock, managed databases/Redis, cloud observability, remote state, domains, or any other potentially billable resource without explicit user approval. The final `pnpm demo` must start/seed or verify the zero-cost stack and demonstrate the flagship recovery, approval, replay, MCP, and multi-agent scenarios without billing credentials.

## Explicitly deferred beyond project

Multi-region active-active writes, formal compliance certification, 24/7 staffed operations, arbitrary untrusted code/browser automation, marketplace/billing/mobile, and any scaling topology not supported by measured demand. Document future triggers rather than speculative implementation.
