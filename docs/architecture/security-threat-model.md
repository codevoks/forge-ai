# Security and threat model

## Security axiom

Application security policy outranks model output. Models and retrieved/external content are untrusted decision inputs, never principals, policy engines, or authorization sources.

## Assets

Tenant data, objectives, evidence, workflow history, credentials, tool capabilities, approval authority, model prompts/outputs, budgets, audit history, code/deployment integrity, and availability/cost capacity.

## Trust boundaries

```text
user/browser | web | API/policy | database/queue | worker/runtime
                                     | model provider
                                     | local tool/integration
                                     | MCP server
                                     | third-party content
```

Every crossing authenticates its caller where possible, validates typed/size-bounded data, propagates tenant/correlation identity, labels trust/provenance, and emits sanitized audit evidence. Queue possession alone grants no authority; workers reload durable scope and policy.

## Authorization model

- OIDC authenticates humans; short-lived scoped service identities authenticate workloads.
- RBAC grants broad tenant/workspace actions; capability/attribute checks restrict concrete resources, tools, risks, and approvals.
- All access is tenant/workspace scoped in the service/repository contract and reinforced with PostgreSQL row-level security when introduced.
- The database connection sets transaction-local actor/tenant context; privileged migration/maintenance roles are distinct from runtime roles.
- Default deny. List endpoints, exports, events, traces, and indirect object references receive the same scope checks as primary resources.
- Emergency policy can tighten a pinned run. Loosening privileges requires an explicit new authorization/version, never model inference.

## Tool and approval security

- Tools are code/admin-registered immutable versions with input/output schema, risk, side-effect class, permission, timeout, retry, idempotency, network/secret needs, and output limit.
- The planner sees only an allowlisted projection. A hallucinated/unlisted/version-mismatched tool fails closed.
- Canonical arguments are schema-validated, normalized, policy-checked, and hashed. Confused-deputy fields such as tenant/user/account are derived from actor context, not accepted blindly from model arguments.
- High-risk effects require approval after authorization. Approval is bound to action hash, run, tool version, canonical arguments, risk, expiry, and eligible approver; argument change invalidates it.
- Separation of duties is policy-configurable. Approval never grants missing tool/user permissions.
- Tool output is data with provenance. It cannot change system instructions, permissions, budgets, or allowed tools.

Current typed-tool runtime implementation enforces the early subset of this model with code-registered tools, strict Pydantic input/output schemas, run-scoped grants, risk labels, local deterministic adapters, invocation action hashes, idempotency keys, `outcome_unknown` recording for ambiguous simulated effects, RLS-protected invocation/evidence inspection, and explicit trust labels such as `untrusted_tool_output`. High-risk irreversible side effects, planner-selected calls, MCP resources, and live providers remain unavailable until their owning phases.

Current structured-planning implementation adds a provider-neutral `ModelProvider` port, deterministic fake planner, optional live-provider adapter that fails closed while external integrations are disabled, prompt/schema version registry, bounded context builder, strict structured-output parser, semantic DAG/tool validation, immutable `plan_versions`, RLS-protected `model_calls`, and execution events for plan acceptance/rejection. The planner may propose only; it cannot execute tools, increase permissions, change budgets, or mutate tasks. Hallucinated tool names/versions, cyclic DAGs, malformed output, model refusal, cross-tenant reads, viewer planning attempts, and prompt-injection attempts are covered by adversarial tests.

Current human-approval implementation adds code-enforced exact-action approval for `simulated_effect` tools. A worker records the invocation intent, hashes canonical arguments, creates a pending approval request, moves the task to `waiting_approval`, and stops before adapter execution. An eligible approver must approve the exact current request version. Self-approval, viewer approval, outsider visibility, stale versions, mutated binding hashes, and expired approvals fail closed. Approval does not grant missing tool/user permissions; it only releases a previously authorized action. Network and secret boundary primitives are present for future egress-capable tools: local SSRF-denial cases reject HTTP, loopback, link-local metadata, and private IP targets; fake secret resolution returns only `secretref://` metadata plus `[redacted]` material.

Current bounded-agent implementation runs model-controlled iteration inside one durable task with explicit budgets and a reusable adversarial suite. The fake model can propose `tool_call`, `complete`, `fail`, or `request_replan`, but application code validates the schema, exact run grants, strict tool arguments, citations, iteration/tool/model-call budgets, and no-progress limits on every iteration. Agent completions need persisted evidence citations. Ungranted tools, unsupported citations, replan requests, repeated invalid decisions, and step limits fail closed. Prompt-injected objectives and untrusted tool outputs are treated as data; they cannot silently change policy, grants, budgets, approvals, or tenant scope.

Current LangGraph comparison implementation adds an alternate local `StateGraph` engine for the same bounded agent task. LangGraph node routing, reducers, checkpoints, and approval-interrupt representation are treated as orchestration mechanics, not authority. Forge still reloads tenant-scoped run/task state, validates model decisions, enforces exact tool grants and schemas, consumes approval gates, tracks budgets, records evidence, and commits terminal transitions in application code. Mirrored `workflow_engine_checkpoints` are sanitized, RLS-protected comparison/debug evidence and cannot be supplied by a client to resume, authorize, or mutate execution.

Current MCP interoperability implementation adds a real JSON-RPC MCP client (local stdio subprocess and remote Streamable HTTP) behind the same `MCPClientPort` used by discovery, health checks, and invocation. Discovery always writes a quarantined `mcp_tool_mappings` row (`status='discovered'`); nothing is resolvable as an executable tool until an administrator explicitly reviews the exact schema hash and enables it, at which point Forge creates a normal `origin='mcp'` `tool_versions` row that then passes through the identical registry/grant/policy/approval/evidence machinery as code-registered tools. MCP tool output is always labeled `untrusted_tool_output`, independent of local-vs-remote trust level. Local stdio servers may only launch an explicit allowlisted Forge-owned module; remote HTTP servers reuse the Phase 6 `NetworkPolicy` SSRF denial list and additionally re-resolve/re-validate the target host on every call, and stay off the zero-cost path unless external integrations are explicitly enabled. A schema/capability change detected on re-discovery retires the previously enabled tool version (`status='drifted'`) rather than mutating it, so pinned runs and the run-scoped grant snapshot stay safe; re-enabling creates a new immutable version. A suspicious-description/output heuristic flags content for the human reviewer only and is never treated as the security boundary — the boundary is the untrusted trust label plus the unchanged approval/grant machinery below it.

Current multi-agent implementation adds isolated parallel specialists plus a deterministic synthesizer, both represented as ordinary DAG tasks so the existing durable/security architecture applies unchanged. A specialist's role identity (`tasks.agent_role`) comes only from the published, server-authored workflow step definition, never from model output, and can only name a role in the code-owned `SPECIALIST_ROLES` catalog; an unrecognized role is rejected before any task is persisted. A deterministic, code-owned `Router` (never a model call) narrows a run's specialists to the objective-relevant ones by keyword match, and this filtering happens in application code before `RunRepository.create_run` ever writes a task — the router's output is enforced by Forge, not merely proposed and trusted. Each specialist keeps the exact same run-scoped `allowed_tools`/budget/approval/evidence boundary as a Phase 7 single agent; nothing broadens a specialist's authority because it is running alongside siblings, and one specialist can never call a tool only a sibling was granted (the task-level `allowed_tools` check enforces this independently of what any other task in the same run holds). Evidence read by `AgentRuntime`/`SpecialistAgentRuntime` is now scoped to the specialist's own `task_id`, not merely the run, closing a cross-specialist evidence-contamination path that a single-agent-per-run design had never needed to close. A specialist's safe termination (budget exhaustion, repeated invalid decisions, or the model giving up) is durable-task-level success carrying a soft `outcome=safe_failure` result, never a task failure — this lets the deterministic synthesizer aggregate a partial result from the specialists that did produce one; a genuine infrastructure failure is not caught this way and still fails the task/run through the unchanged Phase 3 path. The synthesizer never calls a model or a tool: it only reads already-validated `SpecialistResult` payloads from prerequisite tasks' own durable results (the same storage every task result already uses) and combines them with plain code, which structurally prevents a synthesizer from fabricating a consensus the specialists never reached. There is no delegation primitive in the agent decision schema (`tool_call`/`complete`/`fail`/`request_replan` only), so recursive delegation and runaway agent spawning are structurally impossible rather than merely policy-denied; fan-out width is additionally bounded by a small code constant. Cancellation, retries, idempotency, tenant RLS, and dead-lettering are entirely the unchanged Phase 3 mechanisms operating on ordinary tasks.

## Prompt-injection controls

1. Keep policy/tool capability outside natural-language prompts and enforce it after every model decision.
2. Separate trusted instructions from quoted untrusted objective, retrieved documents, web pages, MCP descriptions, and tool outputs.
3. Minimize context and privileges; never expose unrelated secrets or tools.
4. Validate structured output against strict schemas, enums, graph bounds, capability envelopes, and semantic rules.
5. Require citations/evidence for consequential claims and show provenance to approvers.
6. Detect/flag injection indicators for evaluation/triage, but do not treat classifiers as the security boundary.
7. Encode data at output sinks; do not render raw HTML/Markdown/URLs with active behavior.

## Threat/control register

| Threat | Preventive controls | Detection/recovery |
|---|---|---|
| Cross-tenant IDOR | scoped repositories, composite FKs, RLS, opaque IDs | negative matrix tests, audit anomalies |
| Permission/approval bypass | centralized deterministic policy, exact action binding, transactional consume | denied-decision audit, race tests |
| Prompt/tool-output injection | trust labels, context separation, schema/capability enforcement | adversarial eval suite, provenance UI |
| Privilege escalation/confused deputy | derive scope server-side, least-privilege service roles, no model policy | capability-denial metrics |
| Secret exfiltration | secret references/vault, redaction, destination allowlists, no secret prompts/events | egress/audit alerts, rotation playbook |
| SSRF/malicious URL | deny private/link-local/metadata ranges, DNS/IP revalidation, scheme/port/redirect limits, egress proxy where needed | network denial logs, integration disable |
| Replay/duplicate effects | nonce/action hash/expiry, idempotency ledger, safe replay mode | duplicate/reconciliation alerts |
| Denial of wallet/runaway loops | admission/rate/token/currency/tool/iteration/deadline budgets | budget alarms, kill switch, tenant suspension |
| Queue forgery/tampering | private network/TLS/auth, minimal signed/versioned envelope where warranted, DB revalidation | unknown-message quarantine |
| Dependency/supply chain | lockfiles, scanning, pinned CI actions/images, provenance/SBOM later | CI findings and upgrade policy |
| Audit/log injection or leakage | structured logs, escaping, field allowlists, redaction, access/retention controls | canary tests, restricted exports |

## Secret and integration model

The database stores credential metadata and an external secret-manager reference, never reusable secret material. Workers resolve secrets just in time under a scoped workload identity; values are not passed through queues, prompts, checkpoints, events, traces, or exceptions. Local development uses ignored environment files only. Rotation/revocation makes integrations unavailable safely.

## Data lifecycle

Every stored payload category declares owner, purpose, read/write principals, retention, deletion/export behavior, and redaction. Raw model/tool bodies use shorter retention than normalized evidence/events. Legal/audit retention conflicts must be explicit. Deletion is tenant-scoped and produces a tombstone/audit event without retaining deleted secret content.

## Security release gates

No phase passes with known cross-tenant access, model-controlled authorization, unbound approval, logged secret, unbounded loop/cost, replayed effect by default, or an external-fetch tool without network destination controls. Threat model and abuse cases are updated whenever a new trust boundary appears.

## Current phase-level security classification

| Area | Classification | Evidence |
|---|---|---|
| Approval exact-action binding | Protected and verified | Binding hash recomputation rejects modified invocation arguments |
| Separation of duties | Protected and verified | Requester self-approval returns `approval_self_forbidden` |
| Approver authorization | Protected and verified | Viewer approval returns `approval_decision_forbidden`; outsider list returns no rows |
| Replay/stale approval versions | Protected and verified | Duplicate idempotency replay is stable; second decision with stale version is rejected |
| Expiry fail-closed behavior | Protected and verified | Expired approval returns `approval_expired` and fails the run/task without executing the effect |
| Approval table tenant isolation | Protected and verified | RLS hides approval rows without transaction scope |
| SSRF-ready URL boundary | Protected and verified for current primitive | Reusable adversarial URL corpus denies HTTP, loopback, link-local metadata, and private IPs |
| Secret material leakage | Protected and verified for current primitive | Fake resolver returns secret reference and `[redacted]`, never secret material |
| Planner-selected approval/tool execution | Not applicable yet | Planner proposals are still not executable |
| Real external side effects | Not applicable yet | Only deterministic local simulated effects exist |
| Bounded agent tool authority | Protected and verified | Agent `unauthorized_tool` scenario rejects `billing.charge_customer v99` before adapter execution |
| Agent loop/runaway control | Protected and verified | Step-limit scenario terminates after the configured iteration bound |
| Agent evidence citations | Protected and verified | Unsupported completion citation is rejected and fails closed |
| Agent prompt-injection containment | Protected and verified | Prompt-injection scenario uses only granted local `customer_reports.search` and labels evidence `untrusted_tool_output` |
| Execution-time replanning | Implemented but needing deeper final validation | Replan requests are recorded and fail closed; immutable replan lineage expansion is deferred |
| LangGraph engine authority boundary | Protected and verified | LangGraph `unauthorized_tool` scenario rejects `billing.charge_customer v99` through Forge policy before adapter execution |
| LangGraph checkpoint tenant isolation | Protected and verified | `workflow_engine_checkpoints` are hidden without transaction scope and require run authorization for API reads |
| LangGraph bounded autonomy | Protected and verified | LangGraph step-limit scenario fails closed at the configured bound without uncontrolled looping |
| LangGraph prompt-injection containment | Protected and verified | LangGraph prompt-injection scenario remains inside granted local tools and records untrusted provenance |
| LangGraph approval interrupt boundary | Protected and verified | LangGraph approval scenario suspends at the Forge exact-action approval gate and resumes only after an eligible approval |
| Hosted LangGraph services | Not applicable yet | Phase 8 uses only the open-source local library; no hosted service or external checkpoint store is configured |
| LangChain provider boundary | Protected and verified | `langchain_fake` wraps the deterministic fake provider through LangChain prompt/runnable primitives; Forge still validates schema, allowed tools, budgets, plan DAG, and model-call cost flags |
| Evaluation result tenant isolation | Protected and verified | Evaluation endpoints require workspace membership and RLS hides cross-tenant evaluation rows |
| Evaluation execution authorization | Protected and verified | Offline suite execution requires `run.create`; viewer execution returns `evaluation_run_forbidden` |
| LangSmith export seam | Protected and verified for zero-cost mode | Default export is a local sanitized artifact with `live_export=false`; `langsmith_export_mode=enabled` fails closed while external integrations are disabled |
| Security/adversarial suite increment | Protected and verified | Offline suite records security-critical LangChain hallucinated-tool denial, prompt-injection containment, and LangGraph step-limit safe failure |
| Live LangSmith account-backed export | Not applicable yet | No approved account or endpoint is configured; live export is opt-in and does not block the zero-cost path |
| Debugger history tenant isolation | Protected and verified | `GET /v1/runs/{run_id}/debugger` returns `404 run_not_found` for a cross-tenant actor and RLS scopes debugger artifacts |
| Debug cursor tampering | Protected and verified | Forged or cross-run debugger cursors return `debug_cursor_invalid`; every cursor request revalidates run/workspace access |
| Debugger payload/output injection | Protected and verified | Debugger snapshots sanitize payloads, preserve redacted lists safely, and React renders values as escaped data rather than active HTML |
| Projection verification integrity | Protected and verified | `debugger_projection_verifications` records event-fold/current-state mismatches as findings; it never mutates authoritative run/task rows |
| Simulation replay safety | Protected and verified | Simulation replay records tripwires showing no real effect adapter calls, no approval reuse, no authoritative state mutation, and zero paid provider calls |
| Unsafe effect replay | Protected and verified | `effect_replay` requests are persisted as `blocked`; arbitrary side-effect replay remains disabled |
| LangGraph checkpoint authority in debugger | Protected and verified | Debugger correlates `workflow_engine_checkpoints` as read-only evidence; framework checkpoint state is explicitly non-authoritative |
| LangSmith/trace export default path | Protected and verified | Local trace export correlates events/model calls/tool invocations/checkpoints with `live_export=false`; live export is blocked while external integrations are disabled |
| MCP discovery quarantine | Protected and verified | A newly discovered mapping is `status='discovered'`; `MCPToolAdapter.invoke` returns `mcp_tool_adapter_missing` for any tool name that is not an enabled, admin-reviewed Forge tool name |
| MCP local process privilege boundary | Protected and verified | `MCPConnectionPolicy` rejects any stdio command outside `ALLOWED_STDIO_MODULES`, including arbitrary interpreters/binaries |
| MCP remote SSRF boundary | Protected and verified | Remote server URLs reuse the Phase 6 SSRF denial corpus; the HTTP transport additionally re-resolves and rejects private/loopback/link-local/metadata addresses on every call, not only at add-server time |
| MCP zero-cost transport gate | Protected and verified | Adding an `http` transport server returns `mcp_remote_transport_disabled` while `FORGE_EXTERNAL_INTEGRATIONS=disabled`; only local stdio servers are reachable on the default path |
| MCP tenant isolation | Protected and verified | `mcp_servers`, `mcp_capability_snapshots`, and `mcp_tool_mappings` are RLS-scoped; a cross-tenant/non-member actor receives `404`/`403` and RLS hides rows without transaction scope |
| MCP administration RBAC | Protected and verified | Only `mcp.admin` (tenant/workspace admin roles) can add/test/discover/enable/disable; viewer and approver attempts return `mcp_admin_forbidden` |
| MCP schema drift safety | Protected and verified | A changed remote schema retires the previously enabled `tool_versions` row (`drifted`); the old pinned version is no longer resolvable until an admin re-reviews and re-enables it as a new version |
| MCP malicious description/output containment | Protected and verified | A suspicious tool description is flagged for review but not auto-blocked; its output is always recorded with `trust_label='untrusted_tool_output'` and never alters policy, grants, or execution |
| MCP tool run-scoped authority | Protected and verified | An enabled MCP tool with no run-scoped `run_tool_grants` row still returns `tool_not_granted`; global enablement never substitutes for a run grant |
| MCP ambiguous outcome handling | Protected and verified | A timeout after the remote request was already sent raises a distinct `MCPTimeoutAfterSendError`, mapped to `outcome_unknown` for operator reconciliation rather than a silent retry or false success |
| Multi-agent forged/unknown role | Protected and verified | A workflow step naming a role outside the code-owned `SPECIALIST_ROLES` catalog is rejected (`agent_role_unknown`) before any task is persisted |
| Multi-agent cross-specialist evidence isolation | Protected and verified | `AgentRepository.recent_evidence` is scoped by `task_id`, not only `run_id`; a completed multi-agent run shows one distinct `evidence_items.task_id` per specialist that collected evidence |
| Multi-agent cross-specialist tool authority | Protected and verified | A specialist's task-level `allowed_tools` is enforced independently of what a sibling specialist in the same run was granted |
| Multi-agent router authority | Protected and verified | The deterministic router's selection is enforced by filtering the workflow graph in application code before task persistence, not merely proposed; routing never uses a model call |
| Multi-agent recursive delegation / runaway spawning | Not applicable — structurally prevented | `AgentDecisionType` has no delegation/spawn primitive; specialists are fixed at workflow-publish time and bounded by `MAX_SPECIALISTS` |
| Multi-agent cyclic delegation | Protected and verified | A cyclic dependency between specialist steps is rejected by the unchanged Phase 2 `DAGValidator` (`workflow_cycle`) |
| Multi-agent synthesizer fabricated consensus | Protected and verified | The synthesizer is deterministic code over already-validated `SpecialistResult` payloads; it never calls a model and cannot invent an agreement |
| Multi-agent partial-failure aggregation | Protected and verified | A specialist's safe termination is a soft `outcome=safe_failure` result; the synthesizer reports `partial_failure=true` and excludes it, and fails closed only when zero specialists produced a usable result |
| Multi-agent cancellation propagation | Protected and verified | Cancelling a run mid-fan-out marks every still-pending specialist and the synthesizer `cancelled` through the unchanged Phase 3 cancellation cascade |
| Multi-agent RBAC and tenant isolation | Protected and verified | Creating a multi-agent run or triggering a strategy comparison requires `run.create`; `strategy_comparisons` is RLS-scoped and hidden without transaction context |
| Budget reservation race/leak | Protected and verified | `BudgetUsageRepository.try_reserve` is a single conditional `UPDATE ... RETURNING`; a concurrency test fires 20 simultaneous reservations against a ceiling of 5 and confirms exactly 5 succeed and usage never exceeds the ceiling |
| Budget tenant isolation and worker-write boundary | Protected and verified | `budget_policies`/`budget_usage_daily`/`budget_reservations` are RLS-scoped by tenant; a write attempted with neither tenant nor worker transaction context is rejected by RLS |
| Budget fail-closed enforcement | Protected and verified | A reservation that would exceed the workspace daily ceiling raises `ProblemError(429, "budget_exceeded")` before the adapter is invoked; no tool/model call proceeds unbudgeted |
| Budget default-zero monetary ceiling | Protected and verified | Auto-provisioned workspace policies cap `max_currency_minor_per_day` at zero; only an explicit higher policy can permit non-zero spend |
| Telemetry secret/credential leakage | Protected and verified | Span attributes pass through the same `sanitize_payload` redaction as events before export; a span carrying a key named like a secret/token is redacted to `[redacted]` in the local JSONL exporter |
| Telemetry exporter-failure isolation | Protected and verified | `SimpleSpanProcessor` catches and logs exporter exceptions internally; a drill with an unwritable export path confirms the wrapped operation still completes |
| Telemetry live export fail-closed default | Protected and verified | The OTLP exporter attaches only when `telemetry_export_mode=enabled` *and* `external_integrations=enabled` *and* an endpoint is configured; the zero-cost default never attempts a network call |
| Telemetry framework/debugger non-authority | Protected and verified | `task.trace_correlated` is marked `authoritative_for_projection=False` in the event catalog; OTel trace context never influences task/run status or scheduling |
| Temporal decision authority | Not applicable — no adoption | Phase 13 rejected Temporal adoption (Q-005); no external workflow-history service exists to forge or manipulate, so "forged temporal state" has no attack surface in this architecture |
| CI dependency/secret supply chain | Protected and verified | `pip-audit`/`pnpm audit` run in CI on every push/PR and fail the build on known vulnerabilities; a dedicated `secret-scan` job (gitleaks) scans full git history; all GitHub Actions are pinned to commit SHAs, not mutable tags |
