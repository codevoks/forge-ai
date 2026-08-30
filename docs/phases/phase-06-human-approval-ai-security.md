# Phase 6 — Human approval and AI security

## Scope

Implement exact-action approval requests/decisions, suspension/resumption, expiry and separation-of-duty policy; enable carefully simulated/high-risk effect path; harden prompt/tool-output/indirect-injection controls, SSRF-ready network policy, secret references, replay protection, and denial-of-wallet boundaries.

## Concepts being learned

Human-in-the-loop as a durable state machine, authorization vs approval, TOCTOU, action binding, trust boundaries, prompt injection, least privilege, SSRF, secret lifecycle, policy/audit design.

## Architecture changes

Policy returns `deny|allow|require_approval`; runtime persists/suspends before effect. Approval decision transaction rechecks actor eligibility, current authorization, expiry, action hash, run state, and cancellation; it consumes once and emits resume work through outbox.

## Components/modules

Approval policy/service; canonical action summary; eligibility/separation-of-duty checker; approval UI/inbox; expiry scanner; security policy/test corpus; trust-aware context renderer; URL/network policy primitive; secret reference resolver fake; emergency kill/tightening policy.

## Data model changes

`approval_requests`, `approval_decisions`, `policy_versions`, `integration_connections` metadata/secret references, budget-policy skeleton; invocation/run/task approval linkage, expiry/action hash/risk/reason/evidence summary/actor fields; unique terminal decision constraint.

## APIs and important interfaces

List/get approval; approve/reject commands with resource version and idempotency; policy/decision audit queries. `ApprovalPolicy.requirement`, `ApprovalService.decide`, `ActionCanonicalizer`, `NetworkPolicy`, `SecretResolver`, `TrustLabel`. No “approve this run generally” for concrete high-risk effects.

## Security requirements

All controls in the threat model: current auth recheck, exact immutable arguments, one-time expiry, CSRF-safe approval UI, separate eligibility, no secret/prompt leakage, model/external content cannot approve or rewrite policy, URL scheme/host/IP/redirect/DNS restrictions, rate/cost/iteration caps, audit every allow/deny/decision.

## Failure scenarios

Double approve; approve vs cancel/expiry race; permissions revoked after request; arguments/tool version changed; self-approval forbidden; worker resumes twice; malicious evidence/Markdown/URL; DNS rebinding/private IP; secret resolver outage/rotation; emergency policy tightens pinned run.

## Testing strategy

Transactional race tests with barriers; full role/capability/tenant matrix; action mutation invalidation; injection/adversarial corpus; rendered-output XSS tests; SSRF URL/DNS unit tests with fakes; secret redaction canaries; duplicate resume/idempotent effect; cost/runaway tests.

## Acceptance criteria

No high-risk effect executes without current auth plus matching valid approval; any mutation invalidates approval; cancellation/revocation wins safely; injection cannot expand capabilities or alter policy; secrets never appear in stored/logged/model payload fixtures; all decisions are explainable and auditable.

## Learning objectives

Design and implement an approval state machine; attack and defend a tool-enabled model system; explain deterministic guardrails and residual risk to an interviewer.

## Coding exercises (private)

1. Exact-action approval policy.
2. Approval/cancel concurrency test.
3. Indirect-injection tool-output test.
4. SSRF-safe URL validator with DNS recheck model.
5. Secret-redaction canary suite.
6. Denial-of-wallet loop/budget test.

## System-design knowledge expected

Defend approval placement, transaction/TOCTOU handling, separation of duties, prompt injection limits, SSRF/egress layers, secret isolation, emergency policy precedence, and why classifiers/LLMs are not enforcement.

## Zero-cost development and demo path

Use the local web/API approval flow, deterministic attack corpus, local/fake notification adapter, secret references, and controlled local network fixtures. The real approval state machine, canonical action binding, authorization recheck, expiry/revocation, SSRF validation, budget limits, audit trail, and injection defenses must run unchanged. Cloud secret managers, hosted egress products, paid scanners, and external messaging services remain optional adapters and cannot be required for security-gate evidence.

## Explicitly deferred

General real external effects until per-tool operational readiness; full cloud secret manager/egress proxy; agent loop integration; MCP-specific trust; organization-specific policy engine; compliance certification.
