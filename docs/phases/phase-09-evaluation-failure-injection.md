# Phase 9 — Evaluation and failure-injection harness

## Scope

Build versioned datasets/scenarios, deterministic fake-model/tool scripts, graders, adversarial/security suites, failure injection, regression comparison, and opt-in live-model runs. Evaluate plans, task success, tool use, approval/permission compliance, recovery, latency/tokens/cost without conflating test types.

## Concepts being learned

Software tests vs behavioral evals vs live evals, golden scenarios, exact/rule/model graders, statistical uncertainty, dataset leakage, reproducibility, experiment design, regression thresholds.

## Architecture changes

Add evaluation runner outside production request path using the same public application ports. Freeze scenario, dataset, engine, prompt, model, tool, policy, and grader versions. Store raw artifacts with controlled retention and normalized metrics with provenance.

## Components/modules

Scenario/dataset registry; deterministic fake scripts; isolated run fixture builder; exact/schema/rule graders; optional model grader clearly labeled; adversarial corpus; fault injector; metrics aggregator/comparator; CLI/report UI; live-eval opt-in guard.

## Data model changes

`evaluation_suites`, `evaluation_cases`, `evaluation_runs`, `evaluation_case_results`, `metric_values`, artifact references; version/config/seed/environment/commit lineage; no fabricated or overwritten results.

## APIs and important interfaces

Start/get evaluation, compare evaluation runs, export sanitized report. `Scenario`, `Grader`, `EvaluationRunner`, `FaultInjector`, `Metric`, `LiveEvaluationGuard`. Production run metrics and eval verdicts remain separate.

## Security requirements

Sanitized non-production fixtures; no real effect tools; permission/approval violations are hard failures; tenant isolation for results; prompt/adversarial content safely rendered; live model credentials opt-in and budgeted; model grader cannot override deterministic security graders.

## Failure scenarios

Flaky/nondeterministic result; grader bug; provider drift; partial suite failure; timeouts; dataset leakage; metric denominator errors; model grader bias; parallel test contamination; live-budget overrun.

## Testing strategy

Meta-test graders on known pass/fail fixtures; deterministic repeatability; mutation tests for security graders; fault scenarios for every failure-model row; confidence/sample labeling for live runs; baseline comparison rules with absolute security thresholds and explicit quality tolerances.

## Acceptance criteria

One command runs offline deterministic suite; reports plan validity/task success/tool precision-recall/unnecessary-invalid-hallucinated calls/approval/permission/recovery/latency/tokens/cost as applicable; security failures cannot average away; live results include config/sample/uncertainty and are never fabricated.

## Learning objectives

Design an eval dataset and graders, diagnose behavioral regressions, inject distributed failures, and explain what a score can and cannot prove.

## Coding exercises (private)

1. Scripted fake-model scenario DSL.
2. Tool-selection precision/recall grader.
3. Plan-validity/security hard-fail grader.
4. Fault injector for crash windows.
5. Regression comparator with sample caveats.
6. Diagnose a deliberately misleading metric.

## System-design knowledge expected

Defend evaluation isolation, versioning, reproducibility, exact/rule/model graders, live sampling, security thresholds, latency/cost measurement, and avoidance of benchmark overfitting.

## Zero-cost development and demo path

Make versioned local datasets, deterministic fake-model/tool scenarios, exact/schema/rule graders, failure injection, and local reports the complete gating evaluation lane. Model graders, hosted evaluation platforms, and live providers are optional, separately labeled, finite-budget runs that cannot affect the zero-cost gate. Default evaluation commands must deny accidental live access and report synthetic versus measured latency/cost provenance explicitly.

## Explicitly deferred

Automated prompt optimization, production A/B rollout, large judge-model dependence, public benchmark claims, multi-agent comparison dataset use until Phase 12, full observability backend.
