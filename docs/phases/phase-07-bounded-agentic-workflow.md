# Phase 7 — Bounded agentic workflow

## Scope

Integrate objective -> structured plan -> persisted tasks -> model decisions -> authorized tools -> evidence -> approval -> result into one end-to-end agentic workflow. Implement explicit bounded perceive/decide/act/observe loop, context updates, termination, constrained replanning, and useful UI. Use the custom runtime only.

## Concepts being learned

Agent vs workflow, bounded autonomy, agent-loop state, evidence-grounded decisions, context compaction, stop/no-progress criteria, replanning, end-to-end distributed debugging.

## Architecture changes

Add an agent-loop task executor inside the deterministic run envelope. Each iteration persists a checkpoint and one structured decision (`tool_call`, `complete`, `fail`, `request_replan`); policy/runtimes validate it. Planner and executor have distinct contracts. Replan creates immutable lineage and cannot expand grants/budgets.

## Components/modules

Agent executor/state reducer; decision schema/validator; context/evidence selector and compactor; termination/no-progress policy; replan coordinator; result synthesizer with citations; end-to-end investigation workflow template; run/evidence/approval UI.

## Data model changes

`agent_iterations` or versioned checkpoint payloads; plan supersession/task lineage; result/evidence citations; counters/deadlines/budget snapshots. Avoid a generic memory store.

## APIs and important interfaces

Run creation accepts objective, template, allowed-tool grants, and bounded budgets; run detail exposes plan/tasks/iterations/evidence/approvals/result safely. `AgentDecision`, `AgentState`, `AgentReducer`, `TerminationPolicy`, `ReplanPolicy`, `ResultSynthesizer`.

## Security requirements

Validate every iteration anew; context/tool outputs remain untrusted; allowed tools fixed or tightened; approval enforced at tool boundary; budgets reserved; citations required for consequential conclusions; safe rendering; cancellation checked before every external boundary.

## Failure scenarios

Repeated invalid/no-progress decisions; contradictory evidence; context overflow; model asks ungranted tool; replan churn; budget/deadline exhaustion; approval rejection/expiry; worker crash at each checkpoint; cancellation mid-loop; result claims unsupported by evidence.

## Testing strategy

Scripted fake-model golden end-to-end cases, checkpoint crash/recovery, loop bounds/no-progress, replan lineage, permission/approval/injection cases, duplicate deliveries, cancellation, evidence-citation validator, UI journey. Live smoke remains opt-in/non-gating until Phase 9 datasets.

## Acceptance criteria

A deterministic fake completes the flagship investigation through durable steps/tools/approval/result; crash recovery resumes from checkpoints without duplicate effect; every loop terminates within all bounds; result cites evidence; model cannot change policy; operator can explain each transition.

## Learning objectives

Build and debug a typed agent loop without a framework; decide which branches belong in code vs model; reconstruct context, termination, and replanning logic.

## Coding exercises (private)

1. Typed perceive/decide/act reducer.
2. Multi-bound termination policy.
3. Relevant-evidence context selector/compactor.
4. Checkpoint crash reconstruction.
5. Constrained replan validator.
6. Unsupported-claim/citation test.

## System-design knowledge expected

Draw end-to-end control/data flow; distinguish plan-time/execution-time decisions; defend checkpoint granularity, context lifecycle, bounded autonomy, no-progress behavior, and model/application responsibilities.

## Zero-cost development and demo path

Run the flagship workflow end to end with the deterministic fake model and local tools while retaining the real planner, persisted DAG/tasks, workers, checkpoints, policy, approval, budgets, evidence, recovery, and termination logic. Scripted model outputs must cover success, invalid decisions, no progress, replanning, rejection, timeout, and cancellation. Live model and paid tool runs are optional non-gating profiles; the recruiter demo requires neither.

## Explicitly deferred

LangGraph implementation, comprehensive eval harness, replay debugger, MCP, multi-agent, Temporal, production scale/cloud. No vague long-term memory or arbitrary autonomous tool discovery.
