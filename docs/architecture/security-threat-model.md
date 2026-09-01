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
