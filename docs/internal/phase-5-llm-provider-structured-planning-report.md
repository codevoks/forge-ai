# Phase 5 — LLM provider abstraction and structured planning report

## Scope completed

Phase 5 implemented the provider-neutral structured planner boundary:

- deterministic fake `ModelProvider` with valid, malformed, hallucinated-tool, cyclic, refusal, and prompt-injection scenarios;
- optional OpenAI-compatible live adapter that fails closed unless external integrations and credentials are explicitly enabled;
- versioned planner prompt/schema registry;
- bounded context builder over run objective, workflow name, active tool projection, and evidence summaries;
- strict structured output parser and semantic plan validator;
- persistent `model_calls`, `plan_versions`, `plan_nodes`, and `plan_edges`;
- idempotent `POST /v1/runs/{run_id}:plan`;
- read APIs for run plan history and model-call ledger;
- web UI controls and inspection cards for validated/rejected plans;
- focused zero-cost `pnpm demo:planning` evidence script.

The planner proposes only. Tool execution loops, automatic task mutation from plan nodes, human approval integration, retrieval/memory, MCP planning, and multi-agent orchestration remain deferred to later phases.

## Architecture notes

The implementation preserves the settled modular-monolith architecture. Planning lives in `apps/api/src/forge_api/application/planning_service.py`, domain planning contracts live in `apps/api/src/forge_api/domain/planning.py`, provider implementations live behind `apps/api/src/forge_api/ports/model.py`, and persistence is isolated in `apps/api/src/forge_api/infrastructure/planning_repositories.py`.

`apps/api/migrations/005_llm_provider_structured_planning.sql` adds the Phase 5 schema with RLS. Prompt/model/plan records are separate so invalid model output remains auditable without becoming an executable plan.

During regression validation, stale ready tasks from test-created runs exposed a genuine outbox weakness: the dispatcher could publish old task messages even when the associated run/task was no longer executable. `OutboxRepository.due_unpublished` now filters task messages to running runs with ready or retry-wait tasks.

## Security classification

| Area | Classification | Evidence |
|---|---|---|
| Authentication and workspace authorization | Protected and verified | `test_viewer_cannot_plan_run`; existing JWT/RBAC tests |
| Tenant/workspace isolation | Protected and verified | `test_mallory_cannot_read_plans_or_model_calls`; `test_planning_tables_are_hidden_without_rls_scope` |
| Prompt injection through objectives/evidence | Protected and verified | `test_prompt_injection_cannot_expand_planner_tool_authority`; UI and CLI demo |
| Hallucinated tool authority | Protected and verified | `test_invalid_model_outputs_are_rejected_without_nodes[hallucinated_tool-not allowed]`; UI demo |
| Malformed/refused/cyclic model output | Protected and verified | planning parser/validator tests and `pnpm demo:planning` |
| Live/billable provider activation | Protected and verified | `test_live_provider_fails_closed_without_explicit_opt_in`; `pnpm demo:planning` |
| Raw model output retention | Implemented but needing deeper final validation | Raw output is hashed/summarized, not stored; final audit should review all future provider paths |
| Tool-call approval from planner output | Not applicable yet | Planner output is not executable in this phase |

No genuine security blocker remains for Phase 5.

## Zero-cost evidence

Default settings require `FORGE_EXTERNAL_INTEGRATIONS=disabled` and `FORGE_MODEL_PROVIDER=fake`. The fake planner makes no network calls and records `estimated_cost_minor: 0`. Live provider selection returns `403 live_model_disabled` unless explicitly opted in.

`pnpm demo:planning` output included:

- `planning_valid`: validated plan, live provider `false`, cost `0`;
- `planning_repairable_malformed`: corrected validated plan;
- `planning_hallucinated_tool`: rejected with `Tool billing.charge_customer v99 is not allowed.`;
- `planning_cyclic_plan`: rejected with acyclic DAG validation;
- `planning_prompt_injection`: validated safe plan using only `customer_reports.search v1`;
- `planning_live_provider_denied`: `403 live_model_disabled`;
- `planning_zero_cost_summary`: `paid_provider_calls: 0`.

## Validation results

- `pnpm --filter @forge/api lint`: passed.
- `pnpm db:migrate`: passed.
- `pnpm db:seed`: passed.
- `pnpm --filter @forge/api test`: passed, 39 selected tests.
- `pnpm --filter @forge/api test:security`: passed, 22 selected security tests.
- `pnpm lint`: passed.
- `pnpm typecheck`: passed.
- `pnpm test`: passed across API, worker, web, config, and shared-types packages.
- `pnpm build`: passed after rerun with local elevated permissions because sandboxed Turbopack process creation was blocked.
- `pnpm demo:planning`: passed.
- Browser demonstration: passed at `http://127.0.0.1:3000/`; showed Alice Admin, Typed Tool Demo run, validated plan v1, prompt-injection-safe validated plan v2, hallucinated-tool rejected plan v3, fake provider, live provider `false`, estimated cost `0`, and persisted plan events.

## Product gate

Passed. This report is paired with the exact completion commit tagged `phase-5` after implementation, validation, user-visible demonstration, and remote verification.

## Hiring-readiness learning gate

Not tested. Product implementation is complete, but owner mastery still requires reconstruction and interview-style explanation of provider abstraction, structured output validation, prompt-injection boundaries, plan persistence, and the distinction between model proposal and application authority.

## Deferred items

- Automatic execution from planner-created plan nodes.
- High-risk approval integration for planner-selected actions.
- Live model quality benchmarking and provider matrix.
- Retrieval/vector memory and MCP-derived context.
- LangGraph comparison.
- Multi-agent planning.
- Final integrated red-team audit across model, tool, approval, MCP, and multi-agent chains.
