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

Current typed-tool runtime implementation enforces the early subset of this model with code-registered tools, strict Pydantic input/output schemas, run-scoped grants, risk labels, local deterministic adapters, invocation action hashes, idempotency keys, `outcome_unknown` recording for ambiguous simulated effects, RLS-protected invocation/evidence inspection, and explicit trust labels such as `untrusted_tool_output`. High-risk irreversible side effects, human approvals, secret resolution, network egress tools, planner-selected calls, MCP resources, and live providers remain unavailable until their owning phases.

Current structured-planning implementation adds a provider-neutral `ModelProvider` port, deterministic fake planner, optional live-provider adapter that fails closed while external integrations are disabled, prompt/schema version registry, bounded context builder, strict structured-output parser, semantic DAG/tool validation, immutable `plan_versions`, RLS-protected `model_calls`, and execution events for plan acceptance/rejection. The planner may propose only; it cannot execute tools, increase permissions, change budgets, or mutate tasks. Hallucinated tool names/versions, cyclic DAGs, malformed output, model refusal, cross-tenant reads, viewer planning attempts, and prompt-injection attempts are covered by adversarial tests.

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
