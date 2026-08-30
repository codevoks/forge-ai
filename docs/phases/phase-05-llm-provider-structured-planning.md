# Phase 5 — LLM provider layer and structured planning

## Scope

Implement provider-neutral model requests/results, deterministic fake models, one opt-in live adapter, structured outputs, bounded plan generation, semantic DAG validation, context construction/token budgeting, normalized usage/errors, and safe limited correction/replanning. Planner produces proposals only; runtime/tools remain authoritative.

## Concepts being learned

Structured generation, provider abstraction, prompts as versioned inputs, planning/decomposition, DAG validation, context selection/compaction, model nondeterminism, token/cost accounting, fake vs live testing.

## Architecture changes

Add `ModelProvider` and `Planner` ports; prompt/schema/version registry; context builder from explicit evidence references; plan validator applies graph/schema/capability/budget rules after model output. Plan versions persist immutably before tasks are instantiated.

## Components/modules

Model provider adapter/fake; structured response parser; planning request/result schemas; prompt registry; context builder; token estimator/budget check; semantic plan validator; bounded correction policy; usage recorder; provider error normalizer.

## Data model changes

`model_calls`, `prompt_versions`, `plan_versions`, `plan_nodes`, `plan_edges`; run pins provider/model/parameters/prompt/schema; usage/token/cost estimate and sanitized input/output references; validation violations and supersession lineage.

## APIs and important interfaces

Run planning command/status/plan inspection; no raw provider proxy. `ModelProvider.complete`, `StructuredModelRequest/Result`, `Planner.plan`, `ContextBuilder.build`, `PlanValidator.validate`, `TokenEstimator`, `PromptRegistry`. Live calls require explicit config and suite labels.

## Security requirements

Model receives least context and only allowed tool projections; no secrets/policy internals; untrusted content delimited/labeled; strict output schemas and semantic validation; model cannot raise budget/capabilities; prompt/output retention/redaction; model endpoint/config allowlist.

## Failure scenarios

Malformed/refusal/truncated output; hallucinated tool/dependency; cyclic/oversized plan; context overflow; rate limit/timeout; provider drift; duplicate model call; partial usage metadata; prompt injection requesting more privilege; repeated correction loop.

## Testing strategy

Deterministic fake scripts for valid/invalid/cycle/hallucination/refusal; plan property tests; golden context snapshots without secrets; bounded correction test; usage/budget tests; provider contract tests; opt-in live smoke/eval clearly separated and metrics recorded, never asserted as deterministic.

## Acceptance criteria

Fake model reproducibly creates validated persisted plans; every invalid plan fails or corrects within bounds; provider SDK stays in adapter; tool/capability expansion is impossible; usage/provenance is recorded; deterministic tests make no network calls.

## Learning objectives

Implement structured planner and fake provider, reason about context quality and validation, debug malformed planning, and distinguish software correctness from behavioral quality.

## Coding exercises (private)

1. Scriptable deterministic fake model.
2. Structured plan schema/parser.
3. Semantic DAG/capability validator.
4. Token-budgeted context selector.
5. Bounded repair loop with no-progress detection.

## System-design knowledge expected

Explain provider abstraction leakage risks, schema vs semantic validation, bounded planning/replanning, context/memory distinctions, prompt versioning, live-eval nondeterminism, and budget reservation.

## Zero-cost development and demo path

The scriptable deterministic fake model is the required default implementation and must drive every planner acceptance, failure, retry, budget, and security scenario without network access. A live adapter is optional, separately configured, explicitly enabled, budget-capped, and excluded from default tests, CI, evaluations, and `pnpm demo`. Bedrock, paid APIs, trial credits, and large local model downloads are not prerequisites. The demo still uses the real prompt/version registry, context builder, structured parser, semantic validator, immutable plan persistence, and usage ledger.

## Explicitly deferred

Automatic tool-execution loop; high-risk approvals; LangGraph; broad provider matrix/Bedrock decision; retrieval/vector memory; prompt optimization based on unevaluated intuition.
