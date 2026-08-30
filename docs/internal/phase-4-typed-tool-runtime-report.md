# Phase 4 — Typed tool runtime completion report

## Scope completed

Phase 4 adds a run-scoped typed tool runtime to the existing durable workflow system. Tool execution is restricted to code-registered tool versions referenced by published workflow steps and granted to a specific run at run creation. The default implementation remains zero-cost by using deterministic local adapters.

Implemented capabilities:

- code-registered tool definitions and immutable versions;
- strict Pydantic input/output validation with unknown-field rejection;
- run-scoped tool grants;
- worker-integrated tool execution for `tool` tasks;
- invocation intent/result ledger with canonical argument hashing, action hashes, idempotency keys, and `outcome_unknown` status;
- evidence provenance records with source, trust label, content hash, and bounded summary;
- read-only API inspection for tool catalog, run invocations, and evidence;
- web UI inspection for tool catalog, typed-tool workflow execution, invocation ledger, and evidence provenance;
- deterministic CLI demonstration through `pnpm demo:tools`.

## Architecture fit

Tool execution stays behind narrow application/domain interfaces. Queue possession does not authorize a tool call: the worker reloads durable task state, verifies the exact run grant, validates schema and risk policy, records invocation intent, and only then invokes the adapter. PostgreSQL remains authoritative; Redis remains disposable coordination. The browser can inspect tool metadata and run evidence, but it cannot execute arbitrary tools.

## Security classification

| Area | Classification | Evidence |
|---|---|---|
| Registered/versioned tool allowlist | Protected and verified | Unknown or unregistered tool references fail closed during workflow publication or execution |
| Strict input schema and unknown-field rejection | Protected and verified | `test_tool_workflow_rejects_unknown_fields_before_adapter_execution` |
| Run-scoped grants | Protected and verified | `test_ungranted_tool_task_fails_safely_without_adapter_execution` |
| Duplicate/idempotent delivery | Protected and verified | `test_duplicate_tool_invocation_reuses_logical_action` |
| Cross-tenant invocation/evidence access | Protected and verified | `test_tool_invocation_and_evidence_rls_block_without_scope`, `test_mallory_cannot_read_tool_invocations_or_evidence` |
| Prompt-injected/untrusted tool output | Protected and verified for current scope | `test_untrusted_tool_output_is_labeled_not_executed_as_instruction`; output is labeled as evidence data, not executable instruction |
| Ambiguous simulated effect | Implemented but needing deeper final validation | `test_simulated_effect_outcome_unknown_is_visible_in_invocation_ledger`; reconciliation workflow is deferred |
| Human approval for real effects | Not applicable yet | Phase 6 owns exact-action approval enforcement |
| Live provider/network/secret/MCP boundaries | Not applicable yet | Later phases own live model providers, secret resolution, network tools, and MCP |

## Zero-cost evidence

The default tool runtime uses deterministic local adapters only. No paid model API, cloud tool, SaaS subscription, purchased domain, or billing credential is required for development, tests, or demonstration. `pnpm demo:tools` asserts loopback-only PostgreSQL/Redis URLs and reports `paid_provider_calls: 0`.

## Validation evidence

Required gates were run before final tagging:

- `pnpm db:migrate`: passed
- `pnpm db:seed`: passed
- `pnpm generate:types`: passed
- `pnpm lint`: passed across API, worker, web, config, and shared types
- `pnpm typecheck`: passed across API, worker, web, config, and shared types
- `pnpm test`: passed; API `31 passed, 18 deselected`, web `1 passed`, worker `1 passed`
- `pnpm test:security`: passed; API `18 passed, 31 deselected`, web `1 passed`
- `pnpm build`: passed across API, worker, web, config, and shared types
- `pnpm demo:tools`: passed; printed normal success, strict-schema denial, `outcome_unknown` failure, and `paid_provider_calls: 0`
- Real user-visible demonstration: passed in local browser at `http://127.0.0.1:3000/`; showed typed tool catalog, selected workflow run success, invocation ledger, action hashes/idempotency keys, and evidence provenance with untrusted tool output labeled as data

## Deferred intentionally

- LLM-planned tool calls;
- irreversible real-world tool effects;
- exact-action human approvals;
- secret-manager backed tool credentials;
- real network egress tools and SSRF controls beyond the current no-network deterministic adapters;
- MCP tool mediation;
- live provider contract tests;
- reconciliation UI/process for `outcome_unknown` invocations.
