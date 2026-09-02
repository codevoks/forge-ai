# Deployment and cloud hardening (Phase 13)

This document describes the reviewable AWS deployment design authored in `infra/terraform/`, the container images in `apps/*/Dockerfile`, and the CI hardening in `.github/workflows/ci.yml`. None of this is applied, provisioned, or required by any default command — the zero-cost local profile (`pnpm demo`) needs none of it. See [zero-cost-demo.md](zero-cost-demo.md) for what the default path actually requires.

## Terraform (`infra/terraform/`)

A flat, reviewable (not deeply nested-module) configuration:

| File | Contents |
|---|---|
| `versions.tf` | Provider requirements (`hashicorp/aws` ~> 5.60, `hashicorp/random` ~> 3.6), no backend block |
| `variables.tf` | Region, environment, sizing inputs; `environment` rejects `"local"` by validation so the zero-cost profile can never be pointed at this config |
| `network.tf` | VPC, public/private subnets across `availability_zone_count` AZs, one NAT gateway per AZ, security groups (ALB public-only; ECS tasks reachable only from the ALB SG; RDS/Redis reachable only from the ECS tasks SG) |
| `database.tf` | RDS Postgres 17, encrypted at rest with a dedicated KMS key, private subnet group, `publicly_accessible = false`, 14-day automated backups, deletion protection in production, credentials in Secrets Manager only |
| `cache.tf` | ElastiCache Redis replication group, encrypted at rest and in transit, private subnet group, automatic failover in production only |
| `iam.tf` | Least-privilege ECS task execution role (image pull, logs, and `secretsmanager:GetSecretValue`/`kms:Decrypt` scoped to exactly the one secret/key this config creates — no wildcard); an empty ECS task role reserved for future AWS SDK calls Forge does not make today |
| `ecs.tf` | Fargate cluster, API/worker task definitions (non-root `10001:10001`, `readonlyRootFilesystem = true`), an ALB with an HTTP->HTTPS redirect and a TLS 1.2+ listener, CloudWatch log groups with 30-day retention |
| `outputs.tf` | ALB DNS name, cluster name, DB/Redis endpoints, the database secret ARN — never a credential value |

No remote backend is configured, so `terraform init` never requires a pre-existing S3 bucket or DynamoDB lock table to exist (Q-005/Q-010 in `decisions.md`: the zero-cost path uses no remote Terraform backend). A production deployment would add one separately, only when a real deployment is explicitly approved.

**Validation performed:** `terraform fmt -check` passes cleanly. `terraform validate` could not be executed in this environment — the development machine had approximately 500MB of free disk space at validation time, insufficient to download the `hashicorp/aws` provider plugin (400MB+). This is a local disk-space constraint, not a network, credentials, or AWS-access issue; `terraform init -backend=false` successfully reached the public Terraform registry and installed the smaller `hashicorp/random` provider before failing on `hashicorp/aws` with `no space left on device`. The configuration was instead reviewed manually, resource by resource, against the AWS provider's documented schema. Re-running `terraform init -backend=false && terraform validate` from `infra/terraform/` once disk space is available is the outstanding verification step.

**Never run without explicit approval:** `terraform plan`/`apply`/`destroy`, or supplying real AWS credentials to this configuration.

## Container images

`apps/api/Dockerfile`, `apps/worker/Dockerfile`, `apps/web/Dockerfile` are multi-stage builds (a builder stage with build tooling, a minimal `*-slim` runtime stage). All three:

- run as a non-root user (`10001:10001`);
- ship only what the runtime needs (a Python venv for api/worker; Next.js's traced `standalone` output for web — not the full `node_modules` tree);
- set `readonlyRootFilesystem = true` at the ECS task-definition level for api/worker (the Dockerfiles themselves don't write to the filesystem after startup).

`apps/worker/Dockerfile` documents a real, pre-existing packaging gap found while writing it: `forge_worker.main` imports `forge_api.*` directly, but `apps/worker/pyproject.toml` does not declare `forge-api` as a dependency — it only works today because local dev installs both packages into one shared venv (`scripts/setup-python.mjs`). The Dockerfile works around this the same way (installing both `./apps/api` and `./apps/worker`) rather than fixing the underlying packaging, which is out of this phase's scope.

**Validation performed:** careful manual review (base image tags, non-root user creation, multi-stage `COPY --from=builder` paths, `next.config.ts`'s `output: "standalone"` compatibility). Live `docker build` was not attempted for any of the three images — see the disk-space note above; pulling `python:3.11-slim`/`node:22.12.0-slim` base images risked pushing an already 96%-full disk to zero. Running `docker build -f apps/api/Dockerfile .` (repeat for worker/web) from the repository root once disk space is available is the outstanding verification step.

## CI hardening (`.github/workflows/ci.yml`)

- Every GitHub Action is pinned to an exact commit SHA (fetched from the GitHub API, verified against the intended version tag), not a mutable version tag: `actions/checkout`, `actions/setup-node`, `pnpm/action-setup`, `gitleaks/gitleaks-action`.
- A new `secret-scan` job runs `gitleaks` against full git history (`fetch-depth: 0`) on every push/PR. Free for personal GitHub accounts (a `GITLEAKS_LICENSE` secret is only required for GitHub Organizations).
- The `quality` job gained two dependency-vulnerability-scanning steps: `pip-audit --skip-editable` (Python) and `pnpm audit --audit-level=high` (JS). Both run after the existing test/security-test steps and fail the build on a known vulnerability.

**Validation performed:** both scan commands were run locally against this repository before being added to CI. `pip-audit` surfaced 31 real vulnerabilities across `cryptography`, `pyjwt`, `pytest`, `python-multipart`, `setuptools`, and `starlette` (a transitive `fastapi` dependency); `pnpm audit` surfaced 39 across `next`, `postcss`, `vitest`, and `turbo`. Every flagged package was upgraded to its minimum safe fix version (not necessarily the latest major release, to bound compatibility risk), and the full monorepo `lint`/`typecheck`/`build`/`test`/`test:security` suite was re-run and confirmed green after each round of upgrades. Both tools now report zero known vulnerabilities. `scripts/setup-python.mjs` had its own hardcoded `pytest`/`pytest-cov` pins independent of `apps/api/pyproject.toml`'s `[dependency-groups]` — a real gap that would have silently reverted the pytest fix on the next `pnpm install`; both are now fixed in lockstep.

## Backup/restore

`pnpm backup-restore-drill` (`scripts/backup-restore-drill.mjs`) runs a real `pg_dump`/`pg_restore` cycle against the local Postgres container: it backs up the live `forge` database, restores it into a throwaway database inside the same container, verifies row counts match across six representative tables, then drops the throwaway database. It never mutates the real database's data. Measured on this machine: ~0.2-0.3s backup, ~1.9s restore, zero row-count mismatches across two runs. This is a local-profile RPO/RTO proxy — one container, no replica, no continuous WAL archiving — not a production SLA claim.

## Capacity

`pnpm capacity-report` (`apps/api/src/forge_api/scripts/capacity_report.py`) is the load/soak drill; see [scale-observability-cost.md](scale-observability-cost.md) for the measured numbers and their caveats, and [decisions.md](decisions.md) Q-005 for how this evidence informed the Temporal no-adoption decision.
