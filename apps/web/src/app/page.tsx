"use client";

import { useState } from "react";
import type { ActorSummary } from "@forge/shared-types";
import {
  advanceRun,
  approveRequest,
  cancelRun,
  createDebugReplay,
  createTraceExport,
  createRun,
  getDebuggerSnapshot,
  getRun,
  getDemoToken,
  getMe,
  getWorkerState,
  listAgentIterations,
  listDeadLetters,
  listEngineCheckpoints,
  listEvidence,
  listEvents,
  listModelCalls,
  listApprovals,
  listPlans,
  listTasks,
  listToolInvocations,
  listTools,
  listWorkflows,
  planRun,
  requeueDeadLetter,
  rejectRequest,
  runRecoveryScan,
  runOfflineEvaluation,
  verifyProjection,
  type ApprovalRequest,
  type AgentIteration,
  type DeadLetter,
  type DebuggerSnapshot,
  type EngineCheckpoint,
  type EvaluationRun,
  type EvidenceItem,
  type ExecutionEvent,
  type ModelCall,
  type PlanVersion,
  type RecoveryScan,
  type RunSummary,
  type TaskSummary,
  type ToolInvocation,
  type ToolSummary,
  type WorkerState,
  type WorkflowVersion
} from "../lib/api";
import { toExecutionState } from "../lib/status";
import { AgentBudgetMeter } from "../components/AgentBudgetMeter";
import { ApprovalPanel } from "../components/ApprovalPanel";
import { ExecutionGraph } from "../components/ExecutionGraph";
import { ExecutionTimeline } from "../components/ExecutionTimeline";
import { IdentityBar, type IdentityOption } from "../components/IdentityBar";
import { Inspector, RawJsonDisclosure, type InspectorTab } from "../components/Inspector";
import {
  Button,
  Eyebrow,
  MetricCell,
  Panel,
  PanelHeading,
  StateBadge,
  Tag
} from "../components/primitives";
import { SecurityState } from "../components/SecurityState";
import { WorkerStatusStrip } from "../components/WorkerStatusStrip";
import { WorkflowPicker } from "../components/WorkflowPicker";

type DemoSubject = "alice" | "ava" | "bob" | "mallory";
type PlanningScenario =
  | "valid"
  | "repairable_malformed"
  | "hallucinated_tool"
  | "cyclic_plan"
  | "refusal"
  | "prompt_injection";
type EngineKind = "custom" | "langgraph";

const IDENTITY_OPTIONS: IdentityOption<DemoSubject>[] = [
  { key: "alice", label: "Alice Admin", hint: "Full workspace administration capabilities" },
  { key: "ava", label: "Ava Approver", hint: "Can decide pending approval requests" },
  { key: "bob", label: "Bob Viewer", hint: "Read-only — cannot create runs or approve" },
  { key: "mallory", label: "Mallory Outsider", hint: "No workspace membership — used to prove tenant isolation" }
];

function hasCapability(actor: ActorSummary | null, capability: string) {
  return Boolean(
    actor?.workspaces.some((workspace) => workspace.capabilities.includes(capability))
  );
}

function classifyToolError(errorType: string | null): "denied" | "exhausted" | "invalid" {
  if (!errorType) return "invalid";
  const key = errorType.toLowerCase();
  if (key.includes("budget")) return "exhausted";
  if (key.includes("polic") || key.includes("permission") || key.includes("auth")) return "denied";
  return "invalid";
}

export default function Home() {
  const [actor, setActor] = useState<ActorSummary | null>(null);
  const [selected, setSelected] = useState<DemoSubject>("alice");
  const [status, setStatus] = useState("Choose a local demo identity.");
  const [error, setError] = useState("");
  const [token, setToken] = useState("");
  const [workflows, setWorkflows] = useState<WorkflowVersion[]>([]);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState("");
  const [selectedEngine, setSelectedEngine] = useState<EngineKind>("custom");
  const [run, setRun] = useState<RunSummary | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const [tools, setTools] = useState<ToolSummary[]>([]);
  const [toolInvocations, setToolInvocations] = useState<ToolInvocation[]>([]);
  const [evidenceItems, setEvidenceItems] = useState<EvidenceItem[]>([]);
  const [plans, setPlans] = useState<PlanVersion[]>([]);
  const [modelCalls, setModelCalls] = useState<ModelCall[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [agentIterations, setAgentIterations] = useState<AgentIteration[]>([]);
  const [engineCheckpoints, setEngineCheckpoints] = useState<EngineCheckpoint[]>([]);
  const [workerState, setWorkerState] = useState<WorkerState | null>(null);
  const [deadLetters, setDeadLetters] = useState<DeadLetter[]>([]);
  const [recovery, setRecovery] = useState<RecoveryScan | null>(null);
  const [evaluationRun, setEvaluationRun] = useState<EvaluationRun | null>(null);
  const [evaluationRunning, setEvaluationRunning] = useState(false);
  const [debuggerSnapshot, setDebuggerSnapshot] = useState<DebuggerSnapshot | null>(null);
  const [debuggerRunning, setDebuggerRunning] = useState(false);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  async function loadIdentity(subject: DemoSubject) {
    setSelected(subject);
    setError("");
    setRun(null);
    setTasks([]);
    setEvents([]);
    setToolInvocations([]);
    setEvidenceItems([]);
    setPlans([]);
    setModelCalls([]);
    setApprovals([]);
    setAgentIterations([]);
    setEngineCheckpoints([]);
    setWorkflows([]);
    setSelectedWorkflowId("");
    setTools([]);
    setWorkerState(null);
    setDeadLetters([]);
    setRecovery(null);
    setEvaluationRun(null);
    setEvaluationRunning(false);
    setDebuggerSnapshot(null);
    setDebuggerRunning(false);
    setSelectedTaskId(null);
    setStatus("Loading signed local token and workspace scope...");
    try {
      const nextToken = await getDemoToken(subject);
      const me = await getMe(nextToken);
      const [workflowVersions, toolCatalog] = await Promise.all([
        listWorkflows(nextToken),
        listTools(nextToken)
      ]);
      const defaultWorkflow =
        workflowVersions.find((workflow) => workflow.name === "Bounded Agent Demo") ??
        workflowVersions.find((workflow) => workflow.name === "Typed Tool Demo") ??
        workflowVersions[0];
      setToken(nextToken);
      setActor(me);
      setWorkflows(workflowVersions);
      setSelectedWorkflowId(defaultWorkflow?.id ?? "");
      setTools(toolCatalog);
      setApprovals(await listApprovals(nextToken));
      await refreshOperations(nextToken, me);
      setStatus("Authenticated through the local OIDC/JWKS path.");
    } catch (caught) {
      setActor(null);
      setToken("");
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Identity request failed safely.");
    }
  }

  async function refreshOperations(activeToken = token, activeActor = actor) {
    if (!activeToken) {
      return;
    }
    const nextWorkerState = await getWorkerState(activeToken);
    setWorkerState(nextWorkerState);
    if (hasCapability(activeActor, "run.recover")) {
      setDeadLetters(await listDeadLetters(activeToken));
    } else {
      setDeadLetters([]);
    }
  }

  async function refreshRunState(runId: string) {
    if (!token) {
      return;
    }
    const nextRun = await getRun(token, runId);
    setRun(nextRun);
    const [nextTasks, nextEvents] = await Promise.all([
      listTasks(token, runId),
      listEvents(token, runId)
    ]);
    setTasks(nextTasks);
    setEvents(nextEvents);
    const [nextPlans, nextModelCalls] = await Promise.all([
      listPlans(token, runId),
      listModelCalls(token, runId)
    ]);
    setPlans(nextPlans);
    setModelCalls(nextModelCalls);
    setApprovals(await listApprovals(token));
    setDebuggerSnapshot(null);
    const hasAgentTask = nextTasks.some((task) => task.kind === "agent");
    setAgentIterations(hasAgentTask ? await listAgentIterations(token, runId) : []);
    setEngineCheckpoints(
      nextRun.engine_kind === "langgraph" ? await listEngineCheckpoints(token, runId) : []
    );
    const hasToolOrAgentTask = nextTasks.some((task) => task.kind === "tool" || task.kind === "agent");
    if (hasToolOrAgentTask) {
      const [nextInvocations, nextEvidence] = await Promise.all([
        listToolInvocations(token, runId),
        listEvidence(token, runId)
      ]);
      setToolInvocations(nextInvocations);
      setEvidenceItems(nextEvidence);
    } else {
      setToolInvocations([]);
      setEvidenceItems([]);
    }
    await refreshOperations();
  }

  async function createDeterministicRun() {
    const selectedWorkflow = workflows.find((workflow) => workflow.id === selectedWorkflowId);
    if (!token || !selectedWorkflow) {
      return;
    }
    setError("");
    setStatus("Creating persisted run and task DAG...");
    try {
      const nextRun = await createRun(token, {
        workspace_id: selectedWorkflow.workspace_id,
        workflow_version_id: selectedWorkflow.id,
        engine_kind: selectedEngine,
        objective:
          selectedWorkflow.name === "Typed Tool Demo"
            ? "Demonstrate typed tool runtime, invocation ledger, and evidence provenance."
            : selectedWorkflow.name === "Bounded Agent Demo"
              ? "Demonstrate bounded agentic workflow with fake model, local tools, citations, and zero cost."
            : "Demonstrate durable local worker execution."
      });
      await refreshRunState(nextRun.id);
      setStatus("Run created and queued. The local worker can execute it asynchronously.");
      window.setTimeout(() => void refreshRunState(nextRun.id), 1500);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Run command failed safely.");
    }
  }

  async function advanceDeterministicRun() {
    if (!run || !token) {
      return;
    }
    setError("");
    setStatus("Advancing one ready task through deterministic in-process execution...");
    try {
      const nextRun = await advanceRun(token, run.id);
      await refreshRunState(nextRun.id);
      setStatus(
        nextRun.status === "succeeded"
          ? "Run succeeded. All task transitions and events are persisted."
          : "One task advanced. Readiness was recalculated from persisted dependencies."
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Advance command failed safely.");
    }
  }

  async function refreshCurrentRun() {
    if (!run) {
      return;
    }
    setError("");
    setStatus("Refreshing run, task, event, and worker state from the API...");
    try {
      await refreshRunState(run.id);
      setStatus("Latest durable state loaded from PostgreSQL.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Refresh failed safely.");
    }
  }

  async function cancelCurrentRun() {
    if (!run || !token) {
      return;
    }
    setError("");
    setStatus("Requesting cancellation through the persisted run state machine...");
    try {
      const nextRun = await cancelRun(token, run.id, "operator requested local demo cancellation");
      await refreshRunState(nextRun.id);
      setStatus("Cancellation converged. Queued work will not start new task execution.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Cancellation failed safely.");
    }
  }

  async function scanRecovery() {
    if (!token) {
      return;
    }
    setError("");
    setStatus("Running bounded recovery scan...");
    try {
      const scan = await runRecoveryScan(token);
      setRecovery(scan);
      await refreshOperations();
      if (run) {
        await refreshRunState(run.id);
      }
      setStatus("Recovery scan completed and persisted its findings.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Recovery scan was denied or failed safely.");
    }
  }

  async function runEvaluationHarness() {
    const workspaceId = actor?.workspaces[0]?.id;
    if (!token || !workspaceId) {
      return;
    }
    setError("");
    setEvaluationRunning(true);
    setStatus("Running offline evaluation suite with LangChain, LangGraph, and local LangSmith artifact...");
    try {
      const nextEvaluationRun = await runOfflineEvaluation(token, workspaceId);
      setEvaluationRun(nextEvaluationRun);
      await refreshOperations();
      setStatus(
        `Evaluation ${nextEvaluationRun.status}. Cases: ${nextEvaluationRun.summary.passed_cases}/${nextEvaluationRun.summary.total_cases}; paid provider calls: ${nextEvaluationRun.summary.paid_provider_calls}.`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Offline evaluation failed safely.");
    } finally {
      setEvaluationRunning(false);
    }
  }

  async function loadDebugger() {
    if (!run || !token) {
      return;
    }
    setError("");
    setDebuggerRunning(true);
    setStatus("Loading sanitized execution history, checkpoints, and trace evidence...");
    try {
      const snapshot = await getDebuggerSnapshot(token, run.id);
      setDebuggerSnapshot(snapshot);
      setStatus(
        `Debugger loaded. Events: ${snapshot.timeline.events.length}; model calls: ${snapshot.model_calls.length}; tool calls: ${snapshot.tool_invocations.length}.`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Debugger load failed safely.");
    } finally {
      setDebuggerRunning(false);
    }
  }

  async function runProjectionVerification() {
    if (!run || !token) {
      return;
    }
    setError("");
    setDebuggerRunning(true);
    setStatus("Folding event history and comparing it with authoritative run/task state...");
    try {
      await verifyProjection(token, run.id);
      const snapshot = await getDebuggerSnapshot(token, run.id);
      setDebuggerSnapshot(snapshot);
      setStatus(
        `Projection verification ${snapshot.projection_verification?.status ?? "unknown"} with ${snapshot.projection_verification?.mismatch_count ?? 0} mismatches.`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Projection verification failed safely.");
    } finally {
      setDebuggerRunning(false);
    }
  }

  async function runReplay(mode: "simulation" | "effect_replay") {
    if (!run || !token) {
      return;
    }
    setError("");
    setDebuggerRunning(true);
    setStatus(
      mode === "simulation"
        ? "Running simulation replay with tripwires against real effects..."
        : "Attempting unsafe effect replay to prove it is blocked..."
    );
    try {
      const replay = await createDebugReplay(token, run.id, mode);
      const snapshot = await getDebuggerSnapshot(token, run.id);
      setDebuggerSnapshot(snapshot);
      setStatus(`Replay ${replay.mode} ended as ${replay.status}. Live state was not mutated.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Replay request failed safely.");
    } finally {
      setDebuggerRunning(false);
    }
  }

  async function exportLocalTrace() {
    if (!run || !token) {
      return;
    }
    setError("");
    setDebuggerRunning(true);
    setStatus("Creating local LangSmith-shaped trace correlation artifact...");
    try {
      const traceExport = await createTraceExport(token, run.id, "local");
      const snapshot = await getDebuggerSnapshot(token, run.id);
      setDebuggerSnapshot(snapshot);
      setStatus(
        `Trace export ${traceExport.status}. Live export: ${String(traceExport.live_export)}; paid calls: ${String(traceExport.artifact.paid_provider_calls ?? 0)}.`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Trace export failed safely.");
    } finally {
      setDebuggerRunning(false);
    }
  }

  async function retryDeadLetter(deadLetterId: string) {
    if (!token) {
      return;
    }
    setError("");
    setStatus("Requeueing sanitized dead letter through operator recovery...");
    try {
      const nextRun = await requeueDeadLetter(token, deadLetterId);
      await refreshRunState(nextRun.id);
      setStatus("Dead letter was requeued. A new outbox message is ready for the worker.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Dead-letter requeue failed safely.");
    }
  }

  async function createPlannerProposal(fakeScenario: PlanningScenario, allowCorrection = true) {
    if (!run || !token) {
      return;
    }
    setError("");
    setStatus(`Generating ${fakeScenario} structured plan with deterministic fake model...`);
    try {
      const result = await planRun(token, run.id, fakeScenario, allowCorrection);
      await refreshRunState(run.id);
      setStatus(
        result.plan.status === "validated"
          ? `Plan v${result.plan.version_number} validated. Provider: fake, live calls: false, cost: 0.`
          : `Plan v${result.plan.version_number} rejected safely: ${result.plan.validation_errors.join(
              "; "
            )}`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Planning command failed safely.");
    }
  }

  async function tryApproveWithCurrentActor(approval: ApprovalRequest) {
    if (!token || !run) {
      return;
    }
    setError("");
    setStatus("Trying approval with the currently selected identity...");
    try {
      await approveRequest(token, approval, "Current actor attempts approval.");
      await refreshRunState(run.id);
      setStatus("Approval succeeded for the current actor.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Approval attempt was denied safely.");
    }
  }

  async function approveAsAva(approval: ApprovalRequest) {
    if (!run) {
      return;
    }
    setError("");
    setStatus("Ava Approver is approving the exact action hash...");
    try {
      const avaToken = await getDemoToken("ava");
      await approveRequest(
        avaToken,
        approval,
        "Ava approves the exact local simulated action."
      );
      await refreshRunState(run.id);
      window.setTimeout(() => void refreshRunState(run.id), 1500);
      setStatus("Approval accepted. The exact action was requeued for the worker.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Ava approval failed safely.");
    }
  }

  async function rejectAsAva(approval: ApprovalRequest) {
    if (!run) {
      return;
    }
    setError("");
    setStatus("Ava Approver is rejecting the exact action hash...");
    try {
      const avaToken = await getDemoToken("ava");
      await rejectRequest(avaToken, approval, "Ava rejects this exact local action.");
      await refreshRunState(run.id);
      setStatus("Approval was rejected and the run failed safely.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Ava rejection failed safely.");
    }
  }

  const canCreateRun = actor?.workspaces.some(
    (workspace) =>
      workspace.id === workflows.find((workflow) => workflow.id === selectedWorkflowId)?.workspace_id &&
      workspace.capabilities.includes("run.create")
  );
  const canRecover = hasCapability(actor, "run.recover");
  const selectedWorkflow = workflows.find((workflow) => workflow.id === selectedWorkflowId);
  const latestPlan = plans[0];
  const latestModelCall = modelCalls[0];
  const runApprovals = run ? approvals.filter((approval) => approval.run_id === run.id) : [];
  const pendingRunApproval = runApprovals.find((approval) => approval.status === "pending");
  const decidedRunApprovals = runApprovals.filter((approval) => approval.status !== "pending");
  const canRunEvaluations = hasCapability(actor, "run.create");
  const evaluationMetrics = evaluationRun
    ? Object.fromEntries(
        evaluationRun.metrics.map((metric) => [metric.metric_name, metric.metric_value])
      )
    : {};
  const failedToolInvocations = toolInvocations.filter((invocation) => Boolean(invocation.error_type));
  const selectedTask = tasks.find((task) => task.id === selectedTaskId) ?? null;

  const inspectorTabs: InspectorTab[] = [];
  if (run) {
    inspectorTabs.push({
      key: "timeline",
      label: "Timeline",
      count: events.length,
      content: <ExecutionTimeline events={events} />
    });

    inspectorTabs.push({
      key: "planner",
      label: "Planner",
      count: plans.length,
      content: (
        <div className="space-y-4">
          <div>
            <Eyebrow>Structured planner</Eyebrow>
            <p className="mt-1 text-sm text-ink-muted">
              The fake model proposes a plan only. Runtime authorization, tools, budgets, and
              execution remain controlled by Forge application code.
            </p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              <Button variant="primary" size="sm" onClick={() => void createPlannerProposal("valid")}>
                Generate valid plan
              </Button>
              <Button size="sm" onClick={() => void createPlannerProposal("repairable_malformed")}>
                Repair malformed output
              </Button>
              <Button size="sm" onClick={() => void createPlannerProposal("prompt_injection")}>
                Prompt-injection scenario
              </Button>
              <Button size="sm" onClick={() => void createPlannerProposal("hallucinated_tool", false)}>
                Reject hallucinated tool
              </Button>
              <Button size="sm" onClick={() => void createPlannerProposal("cyclic_plan", false)}>
                Reject cycle
              </Button>
            </div>
          </div>

          {latestPlan ? (
            <div className="grid gap-3 lg:grid-cols-[1.2fr_0.8fr]">
              <div className="rounded-md border border-line bg-surface-2 p-3.5">
                <div className="flex flex-wrap items-center gap-2">
                  <Tag tone="accent">plan v{latestPlan.version_number}</Tag>
                  <Tag tone={latestPlan.status === "validated" ? "accent" : "danger"}>
                    {latestPlan.status}
                  </Tag>
                </div>
                <p className="mt-2.5 text-sm text-ink-muted">{latestPlan.summary}</p>
                {latestPlan.validation_errors.length > 0 ? (
                  <SecurityState
                    attempt="Structured plan proposal"
                    control="Planner schema and graph validation"
                    decision="invalid"
                    consequence="Plan rejected before persistence"
                    detail={
                      <ul className="list-disc space-y-1 pl-4">
                        {latestPlan.validation_errors.map((validationError) => (
                          <li key={validationError}>{validationError}</li>
                        ))}
                      </ul>
                    }
                  />
                ) : null}
                <div className="mt-3 space-y-2">
                  {latestPlan.nodes.map((node) => (
                    <div key={node.id} className="rounded border border-line bg-surface-0 p-2.5">
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <span className="font-mono text-accent-strong">{node.key}</span>
                        <Tag>{node.kind}</Tag>
                        {node.tool_name ? (
                          <Tag tone="accent">
                            {node.tool_name} v{node.tool_version}
                          </Tag>
                        ) : null}
                      </div>
                      <p className="mt-1.5 text-sm text-ink">{node.title}</p>
                      <p className="mt-0.5 text-xs text-ink-faint">{node.rationale}</p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="rounded-md border border-line bg-surface-2 p-3.5">
                <p className="text-sm font-medium text-ink">Model call evidence</p>
                {latestModelCall ? (
                  <div className="mt-2 space-y-1 text-xs text-ink-muted">
                    <p>
                      Provider: <span className="font-mono text-accent-strong">{latestModelCall.provider}</span>
                    </p>
                    <p>Model: {latestModelCall.model_name}</p>
                    <p>Status: {latestModelCall.status}</p>
                    <p>Tokens: {latestModelCall.total_tokens}</p>
                    <p>Estimated cost minor units: {latestModelCall.estimated_cost_minor}</p>
                    <p>Live provider call: {String(latestModelCall.live_provider)}</p>
                    {latestModelCall.error_type ? (
                      <p className="text-rose-300">
                        {latestModelCall.error_type}: {latestModelCall.error_message}
                      </p>
                    ) : null}
                  </div>
                ) : null}
                {latestPlan.edges.length > 0 ? (
                  <div className="mt-3">
                    <p className="text-xs font-medium text-ink">Plan edges</p>
                    <ol className="mt-1.5 space-y-1 text-xs text-ink-faint">
                      {latestPlan.edges.map((edge) => (
                        <li key={`${edge.from}-${edge.to}`}>
                          <span className="font-mono text-accent-strong">{edge.from}</span> →{" "}
                          <span className="font-mono text-accent-strong">{edge.to}</span>
                        </li>
                      ))}
                    </ol>
                  </div>
                ) : null}
              </div>
            </div>
          ) : (
            <p className="text-sm text-ink-faint">Generate a structured plan to inspect persisted planner output.</p>
          )}
        </div>
      )
    });

    if (agentIterations.length > 0) {
      inspectorTabs.push({
        key: "agent",
        label: "Agent",
        count: agentIterations.length,
        content: (
          <div className="space-y-4">
            <AgentBudgetMeter iterations={agentIterations} />
            <div className="space-y-2">
              {agentIterations.map((iteration) => (
                <div key={iteration.id} className="rounded-md border border-line bg-surface-2 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Tag tone="accent">iteration {iteration.iteration_number}</Tag>
                    <Tag>{iteration.decision_type}</Tag>
                    <Tag tone={iteration.decision_status === "validated" ? "accent" : "danger"}>
                      {iteration.decision_status}
                    </Tag>
                  </div>
                  {iteration.validation_errors.length > 0 ? (
                    <div className="mt-2">
                      <SecurityState
                        attempt={`Agent decision — iteration ${iteration.iteration_number}`}
                        control="Structured decision schema validation"
                        decision="invalid"
                        consequence="Decision rejected; agent must retry within its bounded budget"
                        detail={
                          <ul className="list-disc space-y-1 pl-4">
                            {iteration.validation_errors.map((validationError) => (
                              <li key={validationError}>{validationError}</li>
                            ))}
                          </ul>
                        }
                      />
                    </div>
                  ) : null}
                  <div className="mt-2">
                    <RawJsonDisclosure
                      label={`Iteration ${iteration.iteration_number} raw decision`}
                      data={{
                        counters_snapshot: iteration.counters_snapshot,
                        decision: iteration.decision,
                        result: iteration.result
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )
      });
    }

    inspectorTabs.push({
      key: "tools",
      label: "Tools & evidence",
      count: toolInvocations.length + evidenceItems.length,
      content: (
        <div className="space-y-5">
          <div>
            <Eyebrow>Tool invocation ledger</Eyebrow>
            {toolInvocations.length === 0 ? (
              <p className="mt-2 text-sm text-ink-faint">No tool invocations recorded for this run yet.</p>
            ) : (
              <div className="mt-2 space-y-2">
                {toolInvocations.map((invocation) => (
                  <div key={invocation.id} className="rounded-md border border-line bg-surface-2 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="font-mono text-sm text-accent-strong">
                          {invocation.tool_name} v{invocation.tool_version}
                        </p>
                        <p className="mt-0.5 text-xs text-ink-faint">
                          action hash {invocation.action_hash.slice(0, 16)}… · idempotency{" "}
                          {invocation.idempotency_key}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        <StateBadge state={toExecutionState(invocation.status)} label={invocation.status} />
                        <Tag>{invocation.risk}</Tag>
                      </div>
                    </div>
                    {invocation.error_type ? (
                      <div className="mt-2.5">
                        <SecurityState
                          attempt={`${invocation.tool_name} v${invocation.tool_version} invocation`}
                          control="Typed tool argument, policy, and grant validation"
                          decision={classifyToolError(invocation.error_type)}
                          consequence="Invocation rejected before any effect executed"
                          detail={`${invocation.error_type}: ${invocation.error_message ?? "no further detail"}`}
                        />
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </div>

          <div>
            <Eyebrow>Evidence provenance</Eyebrow>
            {evidenceItems.length === 0 ? (
              <p className="mt-2 text-sm text-ink-faint">No evidence items recorded for this run yet.</p>
            ) : (
              <div className="mt-2 space-y-2">
                {evidenceItems.map((item) => (
                  <div key={item.id} className="rounded-md border border-line bg-surface-2 p-3">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="font-mono text-sm text-accent-strong">{item.source_name}</p>
                        <p className="mt-0.5 text-xs text-ink-faint">
                          {item.source_type} · content hash {item.content_hash.slice(0, 16)}…
                        </p>
                      </div>
                      <Tag tone={item.trust_label === "untrusted_tool_output" ? "warn" : "accent"}>
                        {item.trust_label}
                      </Tag>
                    </div>
                    <div className="mt-2">
                      <RawJsonDisclosure label="Evidence summary" data={item.summary} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )
    });

    if (decidedRunApprovals.length > 0) {
      inspectorTabs.push({
        key: "approvals",
        label: "Approval history",
        count: decidedRunApprovals.length,
        content: (
          <div className="space-y-3">
            {decidedRunApprovals.map((approval) => (
              <ApprovalPanel key={approval.id} approval={approval} />
            ))}
          </div>
        )
      });
    }

    if (engineCheckpoints.length > 0) {
      inspectorTabs.push({
        key: "langgraph",
        label: "LangGraph checkpoints",
        count: engineCheckpoints.length,
        content: (
          <div className="space-y-2">
            <p className="text-sm text-ink-muted">
              Tenant-scoped checkpoint metadata mapped to Forge run/task IDs. Framework graph state is
              inspectable, but never authoritative.
            </p>
            {engineCheckpoints.slice(-6).map((checkpoint) => (
              <div key={checkpoint.id} className="rounded-md border border-line bg-surface-2 p-3">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Tag tone="accent">{checkpoint.node_name}</Tag>
                  <Tag>{checkpoint.namespace}</Tag>
                  <Tag>{checkpoint.engine_version}</Tag>
                </div>
                <p className="mt-1.5 break-all font-mono text-xs text-ink-faint">
                  checkpoint {checkpoint.checkpoint_id.slice(0, 28)}…
                </p>
                <div className="mt-2">
                  <RawJsonDisclosure
                    label="Checkpoint state"
                    data={{ state_summary: checkpoint.state_summary, metadata: checkpoint.metadata }}
                  />
                </div>
              </div>
            ))}
          </div>
        )
      });
    }

    inspectorTabs.push({
      key: "debugger",
      label: "Debugger",
      content: (
        <div className="space-y-4">
          <div>
            <Eyebrow>Execution debugger and safe replay</Eyebrow>
            <p className="mt-1 text-sm text-ink-muted">
              Correlates events, model calls, tool invocations, evidence, and checkpoints. Replay is
              simulation-only by default; unsafe effect replay is blocked.
            </p>
            <div className="mt-3 flex flex-wrap gap-1.5">
              <Button size="sm" variant={debuggerSnapshot ? "secondary" : "primary"} disabled={debuggerRunning} onClick={() => void loadDebugger()}>
                {debuggerRunning ? "Working..." : "Load debugger"}
              </Button>
              <Button size="sm" disabled={!canRecover || debuggerRunning} onClick={() => void runProjectionVerification()}>
                Verify projection
              </Button>
              <Button size="sm" disabled={!canRecover || debuggerRunning} onClick={() => void runReplay("simulation")}>
                Simulation replay
              </Button>
              <Button size="sm" disabled={!canRecover || debuggerRunning} onClick={() => void runReplay("effect_replay")}>
                Prove effect replay blocked
              </Button>
              <Button size="sm" disabled={!canRecover || debuggerRunning} onClick={() => void exportLocalTrace()}>
                Export local trace
              </Button>
            </div>
          </div>

          {debuggerSnapshot ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
                <MetricCell label="Events" value={debuggerSnapshot.timeline.events.length} />
                <MetricCell label="Models" value={debuggerSnapshot.model_calls.length} />
                <MetricCell label="Tools" value={debuggerSnapshot.tool_invocations.length} />
                <MetricCell label="Projection" value={debuggerSnapshot.projection_verification?.status ?? "not run"} />
                <MetricCell label="Paid calls" value={0} />
              </div>

              <div className="grid gap-3 lg:grid-cols-[1.2fr_0.8fr]">
                <div className="rounded-md border border-line bg-surface-2 p-3">
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-medium text-ink">Causal timeline</p>
                    <Tag tone="accent">
                      cursor {debuggerSnapshot.timeline.next_cursor ? "available" : "empty"}
                    </Tag>
                  </div>
                  <div className="mt-2 space-y-1.5">
                    {debuggerSnapshot.timeline.events.slice(-8).map((debugEvent) => (
                      <div key={debugEvent.id} className="rounded border border-line bg-surface-0 p-2">
                        <div className="flex flex-wrap items-center gap-1.5 text-xs">
                          <Tag tone="accent">#{debugEvent.sequence}</Tag>
                          <span className="font-mono text-accent-strong">{debugEvent.event_type}</span>
                          <Tag>v{debugEvent.schema_version}</Tag>
                          <Tag>known {String(debugEvent.catalog_known)}</Tag>
                        </div>
                        <p className="mt-1 break-all font-mono text-[11px] text-ink-faint">
                          payload hash {debugEvent.payload_hash?.slice(0, 24)}… · correlation{" "}
                          {debugEvent.correlation_id.slice(0, 16)}…
                        </p>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="rounded-md border border-line bg-surface-2 p-3">
                  <p className="text-sm font-medium text-ink">Replay and trace evidence</p>
                  <div className="mt-2 space-y-1 text-xs text-ink-muted">
                    <p>Raw payloads exposed: {String(debuggerSnapshot.security_posture.raw_payloads_exposed)}</p>
                    <p>Effect replay enabled: {String(debuggerSnapshot.security_posture.effect_replay_enabled)}</p>
                    <p>
                      Framework state authoritative:{" "}
                      {String(debuggerSnapshot.security_posture.framework_state_authoritative)}
                    </p>
                    <p>Secrets redacted: {String(debuggerSnapshot.security_posture.secrets_redacted)}</p>
                  </div>
                  <div className="mt-2">
                    <RawJsonDisclosure
                      label="Projection, replay, and trace export"
                      data={{
                        projection: debuggerSnapshot.projection_verification,
                        replay: debuggerSnapshot.replay_sessions[0] ?? null,
                        trace_export: debuggerSnapshot.trace_exports[0] ?? null,
                        langgraph_checkpoints: debuggerSnapshot.engine_checkpoints.length,
                        forge_checkpoints: debuggerSnapshot.forge_checkpoints.length
                      }}
                    />
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-sm text-ink-faint">
              Load the debugger to inspect sanitized history, projection status, replay safety, and
              local trace export evidence.
            </p>
          )}
        </div>
      )
    });
  }

  return (
    <main className="relative min-h-screen bg-surface-0">
      <div
        className="pointer-events-none fixed inset-0 opacity-70"
        style={{
          background:
            "radial-gradient(circle at 18% -10%, rgba(167,139,250,0.10), transparent 34rem), linear-gradient(180deg, var(--color-surface-0) 0%, #050507 50%)"
        }}
      />
      <div className="relative mx-auto max-w-6xl space-y-4 px-6 py-8">
        <header>
          <Eyebrow>Forge AI control plane</Eyebrow>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-ink">
            Identity, tenancy, and durable local workflow execution
          </h1>
        </header>

        <IdentityBar
          options={IDENTITY_OPTIONS}
          selected={selected}
          actor={actor}
          status={status}
          error={error || null}
          onSelect={(subject) => void loadIdentity(subject)}
        />

        {actor ? (
          <Panel>
            <PanelHeading eyebrow={actor.email} title={actor.display_name} />
            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-[repeat(auto-fit,minmax(240px,1fr))]">
              {actor.workspaces.map((workspace) => (
                <div key={workspace.id} className="rounded-md border border-line bg-surface-2 p-3.5">
                  <h3 className="text-sm font-semibold text-ink">{workspace.name}</h3>
                  <p className="mt-1.5 text-xs text-ink-muted">Role: {workspace.role}</p>
                  <div className="mt-2.5 flex flex-wrap gap-1">
                    {workspace.capabilities.map((capability) => (
                      <Tag key={capability} tone="accent">
                        {capability}
                      </Tag>
                    ))}
                  </div>
                </div>
              ))}
              {actor.workspaces.length === 0 ? (
                <div className="rounded-md border border-line bg-surface-2 p-3.5">
                  <h3 className="text-sm font-semibold text-ink">No accessible workspaces</h3>
                  <p className="mt-1.5 text-xs text-ink-muted">
                    The API returned no tenant-scoped memberships — this identity is correctly isolated
                    from every workspace.
                  </p>
                </div>
              ) : null}
            </div>
          </Panel>
        ) : null}

        {actor && workerState ? (
          <>
            <WorkerStatusStrip
              workerState={workerState}
              recovery={recovery}
              canRecover={canRecover}
              onRefresh={() => void refreshOperations()}
              onRecover={() => void scanRecovery()}
            />
            {canRecover && deadLetters.length > 0 ? (
              <Panel>
                <PanelHeading eyebrow="Recovery" title="Dead-letter recovery" />
                <div className="mt-3 space-y-2">
                  {deadLetters.slice(0, 3).map((deadLetter) => (
                    <div key={deadLetter.id} className="rounded-md border border-line bg-surface-2 p-3">
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="text-sm text-ink">{deadLetter.reason}</p>
                          <p className="mt-1 text-xs text-ink-faint">
                            Payload is sanitized; task input and secrets are not displayed.
                          </p>
                        </div>
                        <Button
                          variant={deadLetter.requeued_at ? "secondary" : "primary"}
                          disabled={Boolean(deadLetter.requeued_at)}
                          onClick={() => void retryDeadLetter(deadLetter.id)}
                        >
                          {deadLetter.requeued_at ? "Requeued" : "Requeue"}
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              </Panel>
            ) : null}
          </>
        ) : null}

        {actor ? (
          <Panel>
            <PanelHeading
              eyebrow="Offline evaluation harness"
              title="LangChain, LangGraph, security, and failure-injection regression"
              description="Runs deterministic model/provider cases, real Forge planner validation, real worker/agent execution, LangGraph checkpointing, and a local LangSmith-shaped export artifact. Live providers remain disabled by default."
              action={
                <Button
                  variant="primary"
                  disabled={!canRunEvaluations || evaluationRunning}
                  onClick={() => void runEvaluationHarness()}
                >
                  {evaluationRunning ? "Running..." : "Run offline evaluation"}
                </Button>
              }
            />

            {evaluationRun ? (
              <div className="mt-4 space-y-4">
                <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
                  <MetricCell label="Status" value={evaluationRun.status} />
                  <MetricCell
                    label="Cases"
                    value={`${String(evaluationRun.summary.passed_cases)}/${String(evaluationRun.summary.total_cases)}`}
                  />
                  <MetricCell label="Security" value={`${String(evaluationRun.summary.security_failed_cases)} failed`} />
                  <MetricCell label="LangSmith" value={evaluationRun.exports[0]?.status ?? "none"} />
                  <MetricCell label="Paid calls" value={String(evaluationRun.summary.paid_provider_calls)} />
                </div>

                <div className="grid gap-3 lg:grid-cols-[1.25fr_0.75fr]">
                  <div className="rounded-md border border-line bg-surface-2 p-3.5">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <h3 className="text-sm font-semibold text-ink">Case results</h3>
                      <Tag tone="accent">pass rate {String(evaluationMetrics.case_pass_rate ?? "n/a")}</Tag>
                    </div>
                    <div className="mt-2.5 space-y-2">
                      {evaluationRun.case_results.map((caseResult) => (
                        <div key={caseResult.id} className="rounded border border-line bg-surface-0 p-2.5">
                          <div className="flex flex-wrap items-center gap-1.5">
                            <Tag tone={caseResult.status === "passed" ? "accent" : "danger"}>{caseResult.status}</Tag>
                            <Tag>{caseResult.category}</Tag>
                            <Tag>{caseResult.provider}</Tag>
                            {caseResult.engine_kind ? <Tag>{caseResult.engine_kind}</Tag> : null}
                            {caseResult.security_critical ? <Tag tone="warn">security critical</Tag> : null}
                          </div>
                          <p className="mt-1.5 font-mono text-xs text-accent-strong">{caseResult.case_key}</p>
                          {caseResult.failure_message ? (
                            <p className="mt-1.5 text-xs text-rose-300">{caseResult.failure_message}</p>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="rounded-md border border-line bg-surface-2 p-3.5">
                    <h3 className="text-sm font-semibold text-ink">Framework evidence</h3>
                    <div className="mt-2 space-y-1 text-xs text-ink-muted">
                      <p>LangChain exercised: {String(evaluationRun.summary.langchain_provider_exercised)}</p>
                      <p>LangGraph exercised: {String(evaluationRun.summary.langgraph_exercised)}</p>
                      <p>Live LangSmith export: {String(evaluationRun.summary.langsmith_live_export)}</p>
                      <p>External integrations: {evaluationRun.external_integrations}</p>
                    </div>
                    <div className="mt-2.5">
                      <RawJsonDisclosure
                        label="Metrics and export artifact"
                        data={{ metrics: evaluationMetrics, langsmith_export: evaluationRun.exports[0]?.artifact }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <p className="mt-4 text-sm text-ink-faint">
                Select Alice Admin, then run the offline suite to inspect persisted case results, metrics,
                and export evidence.
              </p>
            )}
          </Panel>
        ) : null}

        {actor && tools.length > 0 ? (
          <Panel>
            <PanelHeading
              eyebrow="Typed tool catalog"
              title="Code-registered tools with versioned schemas and risk labels"
              description="This catalog is read-only. The browser can inspect registered tools, but it cannot execute arbitrary tool calls."
            />
            <div className="mt-4 grid grid-cols-1 gap-2.5 md:grid-cols-3">
              {tools.map((tool) => (
                <div key={tool.id} className="rounded-md border border-line bg-surface-2 p-3">
                  <div className="flex flex-wrap gap-1.5">
                    <Tag tone="accent">v{tool.version}</Tag>
                    <Tag>{tool.risk}</Tag>
                    <Tag>{tool.status}</Tag>
                  </div>
                  <h3 className="mt-2 text-sm font-semibold text-ink">{tool.display_name}</h3>
                  <p className="mt-1.5 text-xs text-ink-muted">{tool.description}</p>
                  <p className="mt-2 break-all font-mono text-[11px] text-accent-strong">{tool.name}</p>
                </div>
              ))}
            </div>
          </Panel>
        ) : null}

        {actor && selectedWorkflow ? (
          <WorkflowPicker
            workflows={workflows}
            selectedWorkflow={selectedWorkflow}
            selectedWorkflowId={selectedWorkflowId}
            selectedEngine={selectedEngine}
            canCreateRun={Boolean(canCreateRun)}
            onSelectWorkflow={(workflowId) => {
              setSelectedWorkflowId(workflowId);
              setRun(null);
              setTasks([]);
              setEvents([]);
              setToolInvocations([]);
              setEvidenceItems([]);
              setPlans([]);
              setModelCalls([]);
              setAgentIterations([]);
              setEngineCheckpoints([]);
              setDebuggerSnapshot(null);
              setSelectedTaskId(null);
            }}
            onSelectEngine={setSelectedEngine}
            onCreateRun={() => void createDeterministicRun()}
          />
        ) : null}

        {run ? (
          <Panel>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <Eyebrow>Current run</Eyebrow>
                <div className="mt-1 flex flex-wrap items-center gap-2.5">
                  <h2 className="text-base font-semibold tracking-tight text-ink">{run.objective}</h2>
                  <StateBadge state={toExecutionState(run.status)} label={run.status} />
                </div>
                <p className="mt-1.5 text-xs text-ink-muted">
                  Version {run.version} · Engine{" "}
                  <span className="font-mono text-accent-strong">{run.engine_kind}</span> · {run.engine_version}
                </p>
              </div>
              <div className="flex flex-wrap gap-1.5">
                <Button size="sm" onClick={() => void refreshCurrentRun()}>
                  Refresh
                </Button>
                <Button
                  size="sm"
                  variant={run.status === "running" ? "danger" : "secondary"}
                  disabled={run.status !== "running"}
                  onClick={() => void cancelCurrentRun()}
                >
                  Cancel run
                </Button>
                <Button
                  size="sm"
                  disabled={run.status !== "running"}
                  onClick={() => void advanceDeterministicRun()}
                >
                  Manual fallback advance
                </Button>
              </div>
            </div>

            <div className="mt-4">
              <ExecutionGraph
                workflow={selectedWorkflow ?? { steps: [], edges: [] }}
                tasks={tasks}
                selectedTaskId={selectedTaskId}
                onSelectTask={setSelectedTaskId}
              />
            </div>

            {selectedTask ? (
              <p className="mt-2 text-xs text-ink-faint">
                Selected step <span className="font-mono text-accent-strong">{selectedTask.step_key}</span> —{" "}
                {selectedTask.name}, status {selectedTask.status}.
              </p>
            ) : null}

            {pendingRunApproval ? (
              <div className="mt-4">
                <ApprovalPanel
                  approval={pendingRunApproval}
                  actions={
                    <>
                      <Button size="sm" onClick={() => void tryApproveWithCurrentActor(pendingRunApproval)}>
                        Try current actor
                      </Button>
                      <Button size="sm" variant="primary" onClick={() => void approveAsAva(pendingRunApproval)}>
                        Approve as Ava
                      </Button>
                      <Button size="sm" variant="danger" onClick={() => void rejectAsAva(pendingRunApproval)}>
                        Reject as Ava
                      </Button>
                    </>
                  }
                />
              </div>
            ) : null}

            {inspectorTabs.length > 0 ? (
              <div className="mt-5 border-t border-line pt-4">
                <Inspector tabs={inspectorTabs} />
              </div>
            ) : null}
          </Panel>
        ) : null}
      </div>
    </main>
  );
}
