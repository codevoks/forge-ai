# LangChain, LangGraph, and LangSmith architecture-placement audit

This audit was added after Phase 8 completion and before Phase 9 implementation. It preserves historical truth: existing `phase-1` through `phase-8` tags and completion reports are not rewritten, moved, or retroactively renamed.

## Placement summary

| Technology | Natural Forge subsystem | Implementation status/location | Enhances earlier subsystem? |
|---|---|---|---|
| LangChain | Model/provider, prompt/message, structured-output, tool interoperability, and composition seams | Schedule genuine implementation in Phase 9 | Yes. It enhances Phase 5 planning/model/tool-boundary work without changing the Phase 5 snapshot. |
| LangGraph | Stateful bounded-agent orchestration: graph state, nodes, conditional edges, reducers, checkpoints, interrupts/HITL, state inspection | First genuine integration completed in Phase 8; evaluate in Phase 9 and connect to debugger/replay in Phase 10 | Yes. It enhances Phase 7 bounded-agent mechanics and was implemented as Phase 8 comparison work. |
| LangSmith | Evaluation datasets, experiments, traces, model/tool/agent observability, and regression comparison | Schedule initial experiment/export seam in Phase 9, trace correlation in Phase 10, and final optional live/self-hosted validation in Phase 13 | Yes. It enhances Phase 5 model calls, Phase 7/8 agent iterations, and Phase 9 evaluations. |

## LangChain decision

LangChain should be integrated around interop/composition, not authority. The best Phase 9 work is a LangChain-backed deterministic path that wraps the existing fake model, prompt/message shape, structured-output parsing boundary, and tool projection. It should prove parity against the native provider path and include security tests showing LangChain cannot:

- expand allowed tools;
- bypass Forge schema validation;
- create or approve side effects;
- change tenant/workspace scope;
- override budgets or state transitions.

This placement is better than forcing LangChain into MCP, multi-agent routing, or worker scheduling because LangChain's value is provider/tool/prompt composition. Forge's durable execution and security model already owns scheduling, approval, and effects.

## LangGraph decision

LangGraph already has a genuine Phase 8 execution role as an explicit `engine_kind=langgraph` strategy for bounded agent tasks. It uses local `StateGraph` nodes, conditional routing, reducers, checkpoint mirroring, and approval-interrupt representation. Forge remains authoritative for persistence, policy, approvals, budgets, tools, evidence, and terminal transitions.

Future work should not duplicate Phase 8 or pretend LangGraph was present earlier. Phase 9 should evaluate custom-vs-LangGraph behavior on frozen cases. Phase 10 should expose LangGraph checkpoint/state inspection beside Forge events in the debugger/replay experience.

This placement is better than replacing the whole durable worker/control plane because Forge's PostgreSQL/outbox/worker architecture is the product authority and learning objective. LangGraph is useful inside the bounded agent orchestration seam.

## LangSmith decision

LangSmith should be treated as observational tooling around evaluations and traces. It should not sit inside the model provider transaction path or worker commit path as a dependency. The right rollout is:

1. Phase 9: add a LangSmith-compatible experiment/export adapter for evaluation runs with local/offline artifacts by default and opt-in external publishing.
2. Phase 10: connect event/model/tool/agent trace correlation and debugger links to the telemetry export seam.
3. Phase 13: finalize optional live/self-hosted LangSmith validation only with explicit owner approval for credentials or endpoint.

LangSmith remains opt-in. The zero-cost demo path must work without a LangSmith account and must fail closed against accidental telemetry egress. If final live/self-hosted LangSmith execution is unavailable because no approved account or endpoint exists, report that as a coverage blocker rather than fabricating evidence.

## Final coverage gate

Final project completion must include the following evidence:

| Technology | Required executed path | Tests | Security boundary tests | Demo | Zero-cost fallback |
|---|---|---|---|---|---|
| LangChain | Deterministic LangChain-backed model/prompt/tool/structured-output interop path | Required | Required | Required | Required |
| LangGraph | Bounded-agent `StateGraph` execution path plus checkpoint/state inspection | Required | Required | Required | Required |
| LangSmith | Opt-in experiment/trace export path and local/offline export fallback | Required where applicable | Required | Required | Required |

Package installation alone is not coverage.
