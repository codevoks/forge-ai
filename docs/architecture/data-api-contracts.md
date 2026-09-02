# Data and API contracts

## Durable data groups

The following are conceptual tables; migrations are introduced in the owning phase.

| Group | Records | Important constraints |
|---|---|---|
| Identity | tenants, workspaces, users, memberships, service_principals | composite tenant/workspace FKs; normalized external subject uniqueness |
| Control | workflow_templates, workflow_versions, tool_definitions, tool_versions, integration_connections, policy_versions, budget_policies, budget_usage_daily, budget_reservations | immutable published versions; secrets stored only as references; budgets reserve-before-work and settle-after (Phase 13) |
| Execution | objectives, runs, plan_versions, tasks, task_dependencies, task_attempts, checkpoints | tenant scope, versions, one active attempt, DAG uniqueness |
| AI/tools | model_calls, tool_invocations, evidence_items | provider-neutral status/usage; trust/provenance; payload size/retention |
| Approval | approval_requests, approval_decisions | action hash, expiry, eligible actor, one terminal decision |
| Engine comparison | workflow_engine_checkpoints | sanitized framework checkpoint metadata mapped to run/task/attempt; not authoritative |
| Evaluation | evaluation_suites, evaluation_cases, evaluation_runs, evaluation_case_results, metric_values, evaluation_exports | tenant-scoped deterministic suites, case verdicts, normalized metrics, and sanitized optional export artifacts |
| Debugging/replay | debugger_projection_verifications, debugger_replay_sessions, debugger_replay_artifacts, debugger_trace_exports | tenant-scoped operator artifacts; simulation replay by default; live trace export opt-in |
| MCP interoperability | mcp_servers, mcp_capability_snapshots, mcp_tool_mappings | tenant/workspace scoped; discovery is quarantined until admin-enabled; enabled mappings link to ordinary origin='mcp' tool_definitions/tool_versions rows |
| Multi-agent patterns | strategy_comparisons | tenant/workspace scoped; correlates two already-durable run IDs (single_agentic, multi_agent_parallel) plus computed metrics; no parallel task/agent state store |
| Reliability | idempotency_records, inbox_messages, outbox_messages, dead_letters, leases | unique logical keys; retry schedule; claim fencing |
| Audit | execution_events, security_audit_events | append-only application permissions; event schema version, cursor ordering, trace metadata, sanitized payload/diff metadata |

All primary identifiers are application-generated UUIDv7 values. Timestamps are UTC `timestamptz`. Mutable aggregates use integer `version` for optimistic concurrency. JSONB is allowed for versioned schemas, provider-neutral payloads, and evidence; relationships, states, ownership, uniqueness, money, and query-critical fields remain relational.

## Transaction boundaries

One transaction must cover each of the following:

- idempotent command lookup/create + aggregate mutation + execution event + outbox;
- run creation + objective snapshot + tasks/dependencies + initial readiness;
- task claim + attempt creation + lease/fencing token;
- attempt result + task/run transition + checkpoint + budget settlement + event/outbox;
- approval request/decision + action-hash validation + invocation/task transition/outbox;
- tool intent + budget reservation before effect; result settlement happens later because external calls cannot join the transaction.

Keep transactions short and never hold database locks across queue, model, tool, MCP, or network calls.

## Repository and unit-of-work ports

```text
UnitOfWork
  begin / commit / rollback
  runs, tasks, attempts, approvals, tools, events, outbox, budgets

RunRepository.get_for_update(scope, run_id)
TaskRepository.claim_ready(scope, worker_id, lease_until) -> Claim | None
EventRepository.append(aggregate, type, actor, cause, sanitized_payload)
OutboxRepository.add(topic, partition_key, envelope)
IdempotencyRepository.begin(scope, operation_key, request_hash)
```

Application services own transaction orchestration. Repositories do persistence only; domain transition functions are pure and independently testable.

## HTTP contract

- Versioned JSON REST under `/v1`; generated OpenAPI is the source for browser client types.
- Browser uses secure HTTP-only same-site session cookies at the web boundary; API receives/verifies a short-lived OIDC access token. Non-browser clients use scoped bearer tokens.
- Every route derives tenant/workspace from verified actor context plus explicit path IDs; never trust tenant IDs in bodies.
- Mutating create/command endpoints require `Idempotency-Key`; reusing a key with a different canonical request hash returns `409`.
- Optimistic updates accept `If-Match`/resource version and return `409` on conflict.
- Errors use a stable problem-details envelope: `code`, safe `message`, `correlation_id`, optional field errors, and retryability. Internal/provider text is not returned raw.
- Cursor pagination is mandatory for collections. Filters are allowlisted and tenant-scoped.
- Initial progress transport is polling plus cursor-based event feeds. SSE remains deferred until measured UI need justifies the extra lifecycle and reconnect surface. Commands never wait for full execution.

Core endpoint families:

```text
POST/GET /v1/runs; GET /v1/runs/{run_id}
POST /v1/runs/{run_id}:cancel
GET /v1/runs/{run_id}/tasks
GET /v1/runs/{run_id}/events
GET /v1/approvals; POST /v1/approvals/{id}:approve|:reject
GET /v1/tools; POST /v1/workflows; POST /v1/workflows/{id}/versions
POST /v1/evaluations; GET /v1/evaluations/{id}
```

Administrative registration endpoints appear only with their owning phase and capability checks.

Implemented deterministic workflow endpoints currently include:

```text
GET /v1/workflows
POST /v1/workflows
GET /v1/workflows/{workflow_version_id}
GET /v1/runs
POST /v1/runs
GET /v1/runs/{run_id}
GET /v1/runs/{run_id}/tasks
GET /v1/runs/{run_id}/events
POST /v1/runs/{run_id}:advance
POST /v1/runs/{run_id}:cancel
GET /v1/operations/worker-state
GET /v1/operations/dead-letters
POST /v1/operations/dead-letters/{dead_letter_id}:requeue
POST /v1/operations/recovery:scan
GET /v1/tools
GET /v1/tools/runs/{run_id}/invocations
GET /v1/tools/runs/{run_id}/evidence
POST /v1/runs/{run_id}:plan
GET /v1/runs/{run_id}/plans
GET /v1/runs/{run_id}/model-calls
GET /v1/runs/{run_id}/agent-iterations
GET /v1/approvals
POST /v1/approvals/{approval_request_id}:approve
POST /v1/approvals/{approval_request_id}:reject
POST /v1/approvals:expire
POST /v1/evaluations
GET /v1/evaluations
GET /v1/evaluations/{evaluation_run_id}
GET /v1/runs/{run_id}/debugger
GET /v1/runs/{run_id}/debugger/events
POST /v1/runs/{run_id}/debugger/projection-verifications
POST /v1/runs/{run_id}/debugger/replays
POST /v1/runs/{run_id}/debugger/trace-exports
GET /v1/mcp/servers
POST /v1/mcp/servers
GET /v1/mcp/servers/{server_id}
POST /v1/mcp/servers/{server_id}:test
POST /v1/mcp/servers/{server_id}:discover
POST /v1/mcp/servers/{server_id}:disable
GET /v1/mcp/servers/{server_id}/mappings
POST /v1/mcp/servers/{server_id}/mappings/{mapping_id}:enable
POST /v1/mcp/servers/{server_id}/mappings/{mapping_id}:disable
POST /v1/multi-agent/comparisons
GET /v1/multi-agent/comparisons
GET /v1/multi-agent/comparisons/{comparison_id}
```

`POST /v1/runs/{run_id}:advance` remains a deterministic manual fallback for local debugging and learning. The primary local execution path now uses the transactional outbox, Redis Streams `QueuePort`, worker claims, attempt leases, checkpoints, retries, dead letters, and recovery scanner. Operator recovery routes require `run.recover`; dead-letter payloads expose only sanitized error summaries, never task inputs, secrets, provider payloads, or raw tool/model output.

Typed tool runtime endpoints expose only catalog and run-inspection views. Forge does not expose a generic browser/API endpoint that can execute arbitrary tools. Tool execution happens only inside a run-scoped task that references a code-registered tool name and version. At run creation, Forge snapshots the exact granted tool versions into `run_tool_grants`; at worker execution time, Forge revalidates the grant, strict input schema, risk class, and deterministic policy before adapter invocation.

Implemented tool tables currently include:

| Table | Purpose | Important constraints |
|---|---|---|
| `tool_definitions` | Stable tool identity and ownership boundary | Code-registered names; tenant/workspace nullable for global tools; status tracked explicitly |
| `tool_versions` | Immutable executable schema/risk contract | Versioned input/output schema, risk, timeout, retryability, and idempotency metadata |
| `run_tool_grants` | Run-scoped allowlist snapshot | One exact tool version grant per run/tool version; queue possession cannot add authority |
| `tool_invocations` | Intent/result ledger | Canonical arguments and action hash; logical invocation uniqueness; statuses include `outcome_unknown` |
| `evidence_items` | Provenance records derived from tool output | Source, trust label, content hash, and bounded summary; raw secrets/provider payloads are not logged |

Implemented structured-planning tables currently include:

| Table | Purpose | Important constraints |
|---|---|---|
| `prompt_versions` | Versioned planner prompt and schema registry | Global or tenant/workspace scoped; active/retired status; template is registered by code and never inferred from model output |
| `model_calls` | Provider-neutral model-call ledger | Request hash and summaries only; normalized status/usage/cost; `live_provider` flag; raw provider output is not stored |
| `plan_versions` | Immutable run-scoped planner proposal | Monotonic version per run; validated/rejected/superseded status; links to prompt and model call |
| `plan_nodes` | Validated plan DAG nodes | Inserted only for validated plans; bounded keys/kinds; tool nodes carry exact name and version |
| `plan_edges` | Validated plan DAG edges | Foreign-keyed to plan nodes; acyclic validation happens before persistence |

`POST /v1/runs/{run_id}:plan` is a planning command, not a provider proxy. It requires `Idempotency-Key`, authorizes the actor against the run workspace, builds a bounded context from the run, allowed tool projection, and evidence summaries, invokes the selected `ModelProvider`, validates structured output, persists the model call and plan version, and appends `plan.validated` or `plan.rejected`. The default provider is the deterministic fake model. Live provider selection fails closed unless external integrations are explicitly enabled.

Implemented human-approval tables currently include:

| Table | Purpose | Important constraints |
|---|---|---|
| `policy_versions` | Workspace policy snapshot for approval requirements | Active policy pins high-risk classes such as `simulated_effect`; loosening policy is not model-controlled |
| `integration_connections` | Local/optional external integration metadata | Stores `secretref://` references only; zero-cost demo uses `local_fake` mode |
| `approval_requests` | One suspended exact action awaiting a human decision | Bound to tenant, workspace, run, task, invocation, tool version, canonical arguments, action hash, risk, requester, expiry, and version |
| `approval_decisions` | Immutable one-decision ledger | Unique decision per request; records approver, reason, request version, and binding hash |

Approval decisions require `Idempotency-Key` and `If-Match`. Approval is a gate, not an authorization source: the worker must already have a run-scoped tool grant and valid schema/risk policy, and the approver must currently have `approval.decide`. Approved requests move the waiting task back to `ready`, mark the invocation `authorized`, and enqueue the exact task for execution. The worker consumes the approval once immediately before adapter execution. Rejected or expired requests fail closed and do not execute the simulated effect.

Implemented bounded-agent tables currently include:

| Table | Purpose | Important constraints |
|---|---|---|
| `agent_iterations` | Durable per-iteration checkpoint ledger for one agent task | Tenant/workspace scoped, monotonic iteration number per task, structured decision type/status, model-call linkage, optional tool/evidence linkage, context hash, counters snapshot |

`agent` workflow steps run inside one durable task, not as graph cycles. The task input declares the agent scenario, objective, explicit bounded budgets, and `allowed_tools`. At run creation, those tool versions are snapshotted into `run_tool_grants`; during execution the model can only propose a structured decision. Forge validates schema, grants, tool arguments, budgets, no-progress limits, and result citations before acting. `GET /v1/runs/{run_id}/agent-iterations` exposes the safe checkpoint ledger to authorized workspace members.

Implemented workflow-engine comparison fields and tables currently include:

| Record | Purpose | Important constraints |
|---|---|---|
| `runs.engine_kind` | Selects `custom` or `langgraph` execution strategy for comparable agent runs | Defaults to `custom`; visible in run inspection; does not change tenant/tool/approval authority |
| `runs.engine_version` | Pins the strategy implementation version used by the run | Examples: `custom-agent-v1`, `langgraph-stategraph-v1` |
| `runs.engine_metadata` | Stores safe selection metadata | No credentials, prompts, raw provider payloads, or secrets |
| `workflow_engine_checkpoints` | Mirrors sanitized LangGraph checkpoint/node metadata | Tenant/workspace scoped with RLS; mapped to Forge run/task/attempt; not used for authorization or scheduling |

`POST /v1/runs` accepts optional `engine_kind` with values `custom` or `langgraph`; omitting it preserves the custom engine. `GET /v1/runs/{run_id}` returns engine metadata. `GET /v1/runs/{run_id}/engine-checkpoints` returns read-only, tenant-scoped checkpoint metadata for authorized workspace members. The endpoint exposes framework comparison evidence only; no API executes arbitrary graph nodes or resumes a run from client-provided framework state.

`POST /v1/runs` also accepts optional `strategy_kind` with values `single_agentic` (default) or `multi_agent_parallel`, orthogonal to `engine_kind`. For `multi_agent_parallel`, the deterministic `Router` filters the target workflow version's specialist agent steps (any `kind="agent"` step whose `input.agent_role` names a code-owned role) down to the objective-relevant ones before any task is persisted, and `GET /v1/runs/{run_id}` returns the routing decision under `strategy_metadata.routing_decision`. `POST /v1/multi-agent/comparisons` runs one frozen local objective through both strategies end to end and persists a `strategy_comparisons` row with measured metrics for each (task success, model/tool call counts, elapsed seconds, task status counts) and explicit statistical caveats; `GET /v1/multi-agent/comparisons` and `GET /v1/multi-agent/comparisons/{comparison_id}` expose the tenant-scoped report. No API lets a model or the router create task authority directly — both endpoints only ever narrow or execute an already-published, already-authorized workflow graph.

Implemented evaluation harness tables currently include:

| Table | Purpose | Important constraints |
|---|---|---|
| `evaluation_suites` | Versioned offline regression suite metadata | Tenant/workspace scoped; unique suite name/version per workspace |
| `evaluation_cases` | Frozen deterministic case definitions | Case key, category, security-critical flag, and expected outcome are versioned data |
| `evaluation_runs` | One persisted suite execution | Status, provider path, engine matrix, external-integration mode, LangSmith export mode, and summary |
| `evaluation_case_results` | Per-case verdict and artifacts | Security-critical failures remain visible and cannot be averaged away |
| `metric_values` | Normalized metrics with provenance | Distinguishes deterministic, synthetic, and measured-local evidence |
| `evaluation_exports` | Optional export seam records | Default LangSmith-shaped export is a local artifact; live export is explicit opt-in |

`POST /v1/evaluations` requires `Idempotency-Key` and `run.create` on the target workspace. The offline suite drives real Forge application services: planner/model-call persistence, LangChain deterministic provider wrapping, LangGraph/custom engine execution, worker safe-failure handling, and export artifact generation. `langsmith_export_mode=enabled` fails closed while external integrations are disabled. `GET /v1/evaluations` and `GET /v1/evaluations/{evaluation_run_id}` are tenant/workspace scoped by actor context and RLS.

Implemented debugger/replay tables currently include:

| Table | Purpose | Important constraints |
|---|---|---|
| `debugger_projection_verifications` | Persisted event-fold vs authoritative-state comparison | Created only by actors with `run.recover`; records mismatches instead of mutating runtime state |
| `debugger_replay_sessions` | Audited replay/simulation request | `simulation` is the default runnable mode; `effect_replay` is persisted as `blocked` in the current implementation |
| `debugger_replay_artifacts` | Sanitized replay artifact/tripwire evidence | Records event hashes, model-call IDs, tool action hashes, and proof that real effect adapters/old approvals were not used |
| `debugger_trace_exports` | Local trace/LangSmith-shaped correlation seam | Default export is a local artifact with `live_export=false`; live export is blocked while external integrations are disabled |

`GET /v1/runs/{run_id}/debugger` requires `run.read` and returns a sanitized operator snapshot: event catalog, cursor timeline, tasks, model calls, tool invocations, evidence, bounded-agent iterations, Forge checkpoints, LangGraph checkpoint mirrors, latest projection verification, replay sessions, trace exports, and explicit security posture flags. It never exposes raw provider/tool payloads or secret material. `GET /v1/runs/{run_id}/debugger/events` supports scope-revalidated cursor resume; forged or cross-run cursors return `debug_cursor_invalid`.

Debugger mutation endpoints require `Idempotency-Key` and `run.recover`. Projection verification folds known event schemas and compares them with current `runs`/`tasks`; a mismatch is reported as an operator finding, not auto-repaired. Replay simulation reads evidence and records a replay artifact with tripwires. It does not call model providers, tool adapters, approval consumption, queues, or state transition code. Effect replay is intentionally disabled and returns a blocked replay session. Trace export creates a sanitized local artifact linking events, model calls, tool invocations, and LangGraph checkpoints; LangSmith/live telemetry export remains explicit opt-in and non-authoritative.

Implemented MCP interoperability tables currently include:

| Table | Purpose | Important constraints |
|---|---|---|
| `mcp_servers` | Admin-managed MCP connection | Tenant/workspace scoped; transport `stdio` or `http`; stdio commands are allowlist-validated, http URLs are SSRF-validated; secrets are references only |
| `mcp_capability_snapshots` | Point-in-time discovery result | Immutable per discovery call; stores the bounded, normalized tool list and a capability hash used for drift detection |
| `mcp_tool_mappings` | Discovery-to-execution review state | One row per `(server, remote_tool_name)`; `status` moves discovered → enabled/disabled/drifted/removed; only `enabled` mappings link to a `tool_definitions`/`tool_versions` row |

`POST /v1/mcp/servers` validates the connection (allowlisted stdio module, or SSRF-checked `https` URL), enforces the zero-cost transport gate (`http` requires `FORGE_EXTERNAL_INTEGRATIONS=enabled`), and requires `mcp.admin` plus `Idempotency-Key`. `POST /v1/mcp/servers/{id}:discover` performs a real MCP `tools/list` call, writes a capability snapshot, and upserts `mcp_tool_mappings` as `discovered`; a schema change on an already-`enabled` mapping retires its `tool_versions` row and flips it to `drifted`, and a tool missing from the new snapshot is marked `removed`. `POST /v1/mcp/servers/{id}/mappings/{mapping_id}:enable` requires `Idempotency-Key`, `If-Match`, and the exact currently-reviewed `schema_hash`; it creates or bumps a `tool_definitions`/`tool_versions` row with `origin='mcp'` and `trust_label='untrusted_tool_output'`, which then flows through the unchanged `run_tool_grants`/`tool_invocations`/`evidence_items`/approval machinery exactly like a code-registered tool. Disabling a mapping or server retires the linked `tool_versions` row; no API executes an MCP tool directly — execution only ever happens inside a run-scoped task that references the exact enabled tool name and version, identical to the Phase 4 typed tool runtime contract.

Implemented multi-agent pattern fields and tables currently include:

| Record | Purpose | Important constraints |
|---|---|---|
| `runs.strategy_kind` | Selects `single_agentic` or `multi_agent_parallel` execution strategy | Defaults to `single_agentic`; orthogonal to `engine_kind`; does not change tenant/tool/approval authority |
| `runs.strategy_version` | Pins the strategy implementation version used by the run | Examples: `single-agentic-v1`, `multi-agent-parallel-v1` |
| `runs.strategy_metadata` | Stores the router's selection decision | For `multi_agent_parallel`, includes `routing_decision` (selected/skipped roles and matched keywords); no credentials or raw model payloads |
| `tasks.agent_role` | Names a specialist's code-owned role | Nullable; set only for specialist agent tasks, from the published workflow step, never from model output |
| `strategy_comparisons` | One persisted comparison report | Tenant/workspace scoped; correlates a `single_agent_run_id` and `multi_agent_run_id` (both ordinary `runs` rows) with measured metrics and explicit caveats |

Specialists are ordinary `kind="agent"` tasks with no dependency edges between them (parallel by construction of the unchanged Phase 2 DAG scheduler) plus one deterministic synthesizer task (`kind="deterministic"`, tagged `input.mode="multi_agent_synthesize"` rather than a new step kind — see migration 012 for why a new kind value was deliberately avoided) that depends on all of them. `SpecialistAgentRuntime` reuses the entire Phase 7 `AgentRuntime` decision loop unchanged; a specialist's safe termination (budget exhaustion, repeated invalid decisions, the model giving up) becomes a durable-task *success* carrying a soft `SpecialistResult(outcome=safe_failure)` payload in `tasks.result`, so the synthesizer can aggregate a partial answer instead of the whole run failing over one specialist's inconclusive result; a genuine infrastructure failure is not caught this way and still fails the task/run through the unchanged Phase 3 path. The synthesizer reads prerequisite specialists' results directly from `tasks.result` via the existing `task_dependencies` edges — the same storage every task result already uses — and never calls a model or a tool.

## Asynchronous envelope

Every outbox/queue message has `message_id`, `schema_version`, `type`, `occurred_at`, `tenant_id`, `workspace_id`, `aggregate_type`, `aggregate_id`, `correlation_id`, `causation_id`, `trace_context`, and a minimal payload of durable IDs. Consumers reject unknown major schema versions, validate scope against database state, and deduplicate on `message_id` plus handler name.

Queues are partitioned/routed by workload and risk (`control`, `model`, `tool_read`, `tool_effect`, `maintenance`) with tenant-aware fair scheduling and concurrency limits. Message priority is bounded to prevent starvation.

## Stable service interfaces

- `AuthorizationService.decide(actor, action, resource) -> PolicyDecision`
- `RiskPolicy.classify(tool_version, canonical_args, context) -> RiskDecision`
- `ApprovalPolicy.requirement(actor, risk, action) -> ApprovalRequirement`
- `BudgetService.reserve/settle/release(scope, operation, estimate/actual)`
- `Planner.plan(PlanningRequest) -> StructuredPlanResult`
- `PlanValidator.validate(plan, envelope) -> ValidatedPlan | violations`
- `ModelProvider.complete(StructuredModelRequest) -> ModelResult`
- `ToolRegistry.resolve(name, version) -> ToolDefinition`
- `ToolExecutor.invoke(AuthorizedInvocation) -> ToolResult`
- `QueuePort.publish/consume/ack/nack/extend_lease`
- `CheckpointStore.save/load`
- `WorkflowEngine.invoke_for_claim(claim) -> task_result`
- `EvaluationRunner.run(suite, providers, engines) -> EvaluationRun`
- `LangSmithExperimentExporter.export(run, results, metrics) -> local_artifact | blocked | exported`
- `DebuggerQuery.timeline(run, cursor) -> sanitized events`
- `ProjectionVerifier.verify(run) -> verification result`
- `ReplayService.create(run, mode) -> simulation | blocked`
- `TraceExportAdapter.export(run, evidence) -> local_artifact | blocked`
- `MCPClientPort.health_check/discover/invoke(connection) -> MCPHealthResult | MCPDiscoveryResult | MCPInvocationResult`
- `Router.route(objective, specialists) -> RoutingDecision` (deterministic, never a model call)
- `SynthesizerRuntime.invoke_for_claim(claim) -> SynthesisResult | raises` (deterministic aggregation, never a model call)
- `TelemetryPort` and `Clock`/`IdGenerator` for deterministic tests.

Provider errors are normalized into `invalid_request`, `auth`, `rate_limited`, `transient`, `timeout`, `policy_blocked`, and `unknown`; only explicitly retryable classes enter backoff.

## Schema evolution

Database migrations are forward-only and expand/migrate/contract for live changes. Event/job/API payloads carry versions and use tolerant readers within a declared compatibility window. Published workflow/tool/plan versions are immutable. Breaking tool schemas create a new tool version; in-flight runs remain pinned.
