"use client";

import { useState } from "react";
import type { ActorSummary } from "@forge/shared-types";
import {
  advanceRun,
  approveRequest,
  cancelRun,
  createRun,
  getRun,
  getDemoToken,
  getMe,
  getWorkerState,
  listDeadLetters,
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
  type ApprovalRequest,
  type DeadLetter,
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

type DemoSubject = "alice" | "ava" | "bob" | "mallory";
type PlanningScenario =
  | "valid"
  | "repairable_malformed"
  | "hallucinated_tool"
  | "cyclic_plan"
  | "refusal"
  | "prompt_injection";

const buttonBase =
  "cursor-pointer rounded-full border border-zinc-800 bg-[#0d0d0f] px-3.5 py-2 text-sm font-medium text-zinc-100 transition duration-150 hover:-translate-y-0.5 hover:border-zinc-700 hover:bg-[#141417]";
const activeButton =
  "border-violet-400 bg-gradient-to-br from-violet-400 to-fuchsia-600 text-white shadow-[0_0_0_1px_rgba(167,139,250,0.26),0_12px_28px_rgba(147,51,234,0.28)]";
const panelClass =
  "rounded-[18px] border border-zinc-800 bg-[#0d0d0f]/90 p-4 shadow-[0_18px_60px_rgba(0,0,0,0.24)]";
const cardClass = "rounded-2xl border border-zinc-800 bg-[#141417] p-4";
const pillClass = "rounded-full border border-violet-400/25 bg-violet-400/10 px-2 py-1 text-xs text-violet-200";
const mutedPillClass = "rounded-full border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs text-zinc-300";

function hasCapability(actor: ActorSummary | null, capability: string) {
  return Boolean(
    actor?.workspaces.some((workspace) => workspace.capabilities.includes(capability))
  );
}

export default function Home() {
  const [actor, setActor] = useState<ActorSummary | null>(null);
  const [selected, setSelected] = useState<DemoSubject>("alice");
  const [status, setStatus] = useState("Choose a local demo identity.");
  const [error, setError] = useState("");
  const [token, setToken] = useState("");
  const [workflows, setWorkflows] = useState<WorkflowVersion[]>([]);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState("");
  const [run, setRun] = useState<RunSummary | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const [tools, setTools] = useState<ToolSummary[]>([]);
  const [toolInvocations, setToolInvocations] = useState<ToolInvocation[]>([]);
  const [evidenceItems, setEvidenceItems] = useState<EvidenceItem[]>([]);
  const [plans, setPlans] = useState<PlanVersion[]>([]);
  const [modelCalls, setModelCalls] = useState<ModelCall[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [workerState, setWorkerState] = useState<WorkerState | null>(null);
  const [deadLetters, setDeadLetters] = useState<DeadLetter[]>([]);
  const [recovery, setRecovery] = useState<RecoveryScan | null>(null);

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
    setWorkflows([]);
    setSelectedWorkflowId("");
    setTools([]);
    setWorkerState(null);
    setDeadLetters([]);
    setRecovery(null);
    setStatus("Loading signed local token and workspace scope...");
    try {
      const nextToken = await getDemoToken(subject);
      const me = await getMe(nextToken);
      const [workflowVersions, toolCatalog] = await Promise.all([
        listWorkflows(nextToken),
        listTools(nextToken)
      ]);
      const defaultWorkflow =
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
    const hasToolTask = nextTasks.some((task) => task.kind === "tool");
    if (hasToolTask) {
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
        objective:
          selectedWorkflow.name === "Typed Tool Demo"
            ? "Demonstrate typed tool runtime, invocation ledger, and evidence provenance."
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

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_20%_0%,rgba(167,139,250,0.16),transparent_32rem),linear-gradient(180deg,#09090b_0%,#050505_44%)] px-6 py-8">
      <div className="mx-auto grid max-w-5xl gap-4">
        <section>
          <p className="text-sm text-zinc-400">Forge AI control plane</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-50">
            Identity, tenancy, and durable local workflow execution
          </h1>
        </section>

        <section className={panelClass}>
          <div className="flex flex-wrap items-center gap-3">
            <button
              className={`${buttonBase} ${selected === "alice" ? activeButton : ""}`}
              onClick={() => void loadIdentity("alice")}
            >
              Alice Admin
            </button>
            <button
              className={`${buttonBase} ${selected === "ava" ? activeButton : ""}`}
              onClick={() => void loadIdentity("ava")}
            >
              Ava Approver
            </button>
            <button
              className={`${buttonBase} ${selected === "bob" ? activeButton : ""}`}
              onClick={() => void loadIdentity("bob")}
            >
              Bob Viewer
            </button>
            <button
              className={`${buttonBase} ${selected === "mallory" ? activeButton : ""}`}
              onClick={() => void loadIdentity("mallory")}
            >
              Mallory Outsider
            </button>
          </div>
          <p className="mt-4 text-sm text-zinc-200">{status}</p>
          {error ? <p className="mt-2 whitespace-pre-wrap text-sm text-rose-400">{error}</p> : null}
        </section>

        {actor ? (
          <section className={panelClass}>
            <h2 className="text-xl font-semibold text-zinc-50">{actor.display_name}</h2>
            <p className="mt-2 text-sm text-zinc-400">{actor.email}</p>
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-[repeat(auto-fit,minmax(260px,1fr))]">
              {actor.workspaces.map((workspace) => (
                <article className={cardClass} key={workspace.id}>
                  <h3 className="font-semibold text-zinc-50">{workspace.name}</h3>
                  <p className="mt-3 text-sm text-zinc-400">Role: {workspace.role}</p>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {workspace.capabilities.map((capability) => (
                      <span className={pillClass} key={capability}>
                        {capability}
                      </span>
                    ))}
                  </div>
                </article>
              ))}
              {actor.workspaces.length === 0 ? (
                <article className={cardClass}>
                  <h3 className="font-semibold text-zinc-50">No accessible workspaces</h3>
                  <p className="mt-3 text-sm text-zinc-400">
                    The API returned no tenant-scoped memberships.
                  </p>
                </article>
              ) : null}
            </div>
          </section>
        ) : null}

        {actor && workerState ? (
          <section className={panelClass}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-sm text-zinc-400">Durable worker plane</p>
                <h2 className="mt-1 text-xl font-semibold text-zinc-50">
                  PostgreSQL outbox, Redis queue, leases, checkpoints, and recovery
                </h2>
                <p className="mt-2 text-sm text-zinc-400">
                  Counts are read from the API under the selected identity and workspace scope.
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button className={buttonBase} onClick={() => void refreshOperations()}>
                  Refresh worker state
                </button>
                <button
                  className={`${buttonBase} ${canRecover ? activeButton : "opacity-50"}`}
                  disabled={!canRecover}
                  onClick={() => void scanRecovery()}
                >
                  Run recovery scan
                </button>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-5">
              <article className={cardClass}>
                <p className="text-xs uppercase tracking-[0.2em] text-violet-300">Outbox pending</p>
                <p className="mt-2 text-2xl font-semibold text-zinc-50">
                  {workerState.outbox.unpublished}
                </p>
              </article>
              <article className={cardClass}>
                <p className="text-xs uppercase tracking-[0.2em] text-violet-300">Outbox sent</p>
                <p className="mt-2 text-2xl font-semibold text-zinc-50">
                  {workerState.outbox.published}
                </p>
              </article>
              <article className={cardClass}>
                <p className="text-xs uppercase tracking-[0.2em] text-violet-300">Running</p>
                <p className="mt-2 text-2xl font-semibold text-zinc-50">
                  {workerState.attempts.running ?? 0}
                </p>
              </article>
              <article className={cardClass}>
                <p className="text-xs uppercase tracking-[0.2em] text-violet-300">Checkpoints</p>
                <p className="mt-2 text-2xl font-semibold text-zinc-50">
                  {workerState.checkpoints}
                </p>
              </article>
              <article className={cardClass}>
                <p className="text-xs uppercase tracking-[0.2em] text-violet-300">Dead letters</p>
                <p className="mt-2 text-2xl font-semibold text-zinc-50">
                  {workerState.dead_letters}
                </p>
              </article>
            </div>

            {recovery ? (
              <p className="mt-4 text-sm text-zinc-300">
                Last recovery scan: expired leases {recovery.expired_leases}, due retries{" "}
                {recovery.due_retries}, republished ready tasks{" "}
                {recovery.republished_ready_tasks}.
              </p>
            ) : null}

            {canRecover && deadLetters.length > 0 ? (
              <div className="mt-4 rounded-2xl border border-zinc-800 bg-black/30 p-4">
                <h3 className="font-semibold text-zinc-50">Dead-letter recovery</h3>
                <div className="mt-3 grid gap-2">
                  {deadLetters.slice(0, 3).map((deadLetter) => (
                    <article
                      className="rounded-xl border border-zinc-800 bg-[#0d0d0f] p-3"
                      key={deadLetter.id}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="text-sm text-violet-200">{deadLetter.reason}</p>
                          <p className="mt-1 text-xs text-zinc-500">
                            Payload is sanitized; task input and secrets are not displayed.
                          </p>
                        </div>
                        <button
                          className={`${buttonBase} ${
                            deadLetter.requeued_at ? "opacity-50" : activeButton
                          }`}
                          disabled={Boolean(deadLetter.requeued_at)}
                          onClick={() => void retryDeadLetter(deadLetter.id)}
                        >
                          {deadLetter.requeued_at ? "Requeued" : "Requeue"}
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            ) : null}
          </section>
        ) : null}

        {actor && tools.length > 0 ? (
          <section className={panelClass}>
            <div>
              <p className="text-sm text-zinc-400">Typed tool catalog</p>
              <h2 className="mt-1 text-xl font-semibold text-zinc-50">
                Code-registered tools with versioned schemas and risk labels
              </h2>
              <p className="mt-2 text-sm text-zinc-400">
                This catalog is read-only. The browser can inspect registered tools, but it cannot
                execute arbitrary tool calls.
              </p>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
              {tools.map((tool) => (
                <article className={cardClass} key={tool.id}>
                  <div className="flex flex-wrap gap-2">
                    <span className={pillClass}>v{tool.version}</span>
                    <span className={mutedPillClass}>{tool.risk}</span>
                    <span className={mutedPillClass}>{tool.status}</span>
                  </div>
                  <h3 className="mt-3 font-semibold text-zinc-50">{tool.display_name}</h3>
                  <p className="mt-2 text-sm text-zinc-400">{tool.description}</p>
                  <p className="mt-3 break-all font-mono text-xs text-violet-200">{tool.name}</p>
                </article>
              ))}
            </div>
          </section>
        ) : null}

        {actor && selectedWorkflow ? (
          <section className={panelClass}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-sm text-zinc-400">Published workflow version</p>
                <h2 className="mt-1 text-xl font-semibold text-zinc-50">
                  {selectedWorkflow.name}
                </h2>
                <p className="mt-2 text-sm text-zinc-400">
                  Immutable version {selectedWorkflow.version_number}; persisted DAG with{" "}
                  {selectedWorkflow.steps.length} steps and {selectedWorkflow.edges.length} edges.
                </p>
              </div>
              <button
                className={`${buttonBase} ${canCreateRun ? activeButton : "opacity-50"}`}
                disabled={!canCreateRun}
                onClick={() => void createDeterministicRun()}
              >
                Create selected run
              </button>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {workflows.map((workflow) => (
                <button
                  className={`${buttonBase} ${
                    selectedWorkflowId === workflow.id ? activeButton : ""
                  }`}
                  key={workflow.id}
                  onClick={() => {
                    setSelectedWorkflowId(workflow.id);
                    setRun(null);
                    setTasks([]);
                    setEvents([]);
                    setToolInvocations([]);
                    setEvidenceItems([]);
                    setPlans([]);
                    setModelCalls([]);
                  }}
                >
                  {workflow.name}
                </button>
              ))}
            </div>

            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-4">
              {selectedWorkflow.steps.map((step) => (
                <article className={cardClass} key={step.key}>
                  <p className="text-xs uppercase tracking-[0.2em] text-violet-300">{step.key}</p>
                  <h3 className="mt-2 font-semibold text-zinc-50">{step.name}</h3>
                  <p className="mt-2 text-sm text-zinc-400">{step.kind}</p>
                </article>
              ))}
            </div>
          </section>
        ) : null}

        {run ? (
          <section className={panelClass}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-sm text-zinc-400">Current run</p>
                <h2 className="mt-1 text-xl font-semibold text-zinc-50">{run.objective}</h2>
                <p className="mt-2 text-sm text-zinc-400">
                  Status: <span className="text-violet-200">{run.status}</span> · Version:{" "}
                  {run.version}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button className={buttonBase} onClick={() => void refreshCurrentRun()}>
                  Refresh run state
                </button>
                <button
                  className={`${buttonBase} ${
                    run.status === "running" ? activeButton : "opacity-50"
                  }`}
                  disabled={run.status !== "running"}
                  onClick={() => void cancelCurrentRun()}
                >
                  Cancel run
                </button>
                <button
                  className={`${buttonBase} ${
                    run.status === "running" ? activeButton : "opacity-50"
                  }`}
                  disabled={run.status !== "running"}
                  onClick={() => void advanceDeterministicRun()}
                >
                  Manual fallback advance
                </button>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-4">
              {tasks.map((task) => (
                <article className={cardClass} key={task.id}>
                  <p className="text-xs uppercase tracking-[0.2em] text-violet-300">
                    {task.step_key}
                  </p>
                  <h3 className="mt-2 font-semibold text-zinc-50">{task.name}</h3>
                  <p className="mt-2 text-sm text-zinc-400">Status: {task.status}</p>
                </article>
              ))}
            </div>

            {runApprovals.length > 0 ? (
              <div className="mt-4 rounded-2xl border border-violet-400/20 bg-violet-400/[0.04] p-4">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="text-sm text-zinc-400">Human approval inbox</p>
                    <h3 className="mt-1 font-semibold text-zinc-50">
                      Exact-action approval for simulated effects
                    </h3>
                    <p className="mt-2 text-sm text-zinc-400">
                      Approval is bound to the exact action hash, tool version, arguments, run,
                      task, expiry, and approver eligibility. It does not grant new permissions.
                    </p>
                  </div>
                  {pendingRunApproval ? (
                    <div className="flex flex-wrap gap-2">
                      <button
                        className={buttonBase}
                        onClick={() => void tryApproveWithCurrentActor(pendingRunApproval)}
                      >
                        Try current actor approval
                      </button>
                      <button
                        className={activeButton + " cursor-pointer rounded-full px-3.5 py-2 text-sm"}
                        onClick={() => void approveAsAva(pendingRunApproval)}
                      >
                        Approve as Ava
                      </button>
                      <button
                        className={buttonBase}
                        onClick={() => void rejectAsAva(pendingRunApproval)}
                      >
                        Reject as Ava
                      </button>
                    </div>
                  ) : null}
                </div>

                <div className="mt-4 grid gap-3">
                  {runApprovals.map((approval) => (
                    <article className={cardClass} key={approval.id}>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className={pillClass}>{approval.status}</span>
                        <span className={mutedPillClass}>{approval.risk}</span>
                        <span className={mutedPillClass}>v{approval.request_version}</span>
                      </div>
                      <p className="mt-3 text-sm text-zinc-300">{approval.reason}</p>
                      <p className="mt-2 break-all font-mono text-xs text-violet-200">
                        action hash {approval.action_hash}
                      </p>
                      <pre className="mt-3 max-h-40 overflow-auto rounded-xl border border-zinc-800 bg-black/40 p-3 text-xs text-zinc-300">
                        {JSON.stringify(approval.action_summary, null, 2)}
                      </pre>
                    </article>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="mt-4 rounded-2xl border border-violet-400/20 bg-violet-400/[0.04] p-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-sm text-zinc-400">Structured planner</p>
                  <h3 className="mt-1 font-semibold text-zinc-50">
                    Fake model proposals, real validation, persisted model-call ledger
                  </h3>
                  <p className="mt-2 text-sm text-zinc-400">
                    The model proposes a plan only. Runtime authorization, tools, budgets, and
                    execution remain controlled by Forge application code.
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    className={activeButton + " cursor-pointer rounded-full px-3.5 py-2 text-sm"}
                    onClick={() => void createPlannerProposal("valid")}
                  >
                    Generate valid plan
                  </button>
                  <button
                    className={buttonBase}
                    onClick={() => void createPlannerProposal("repairable_malformed")}
                  >
                    Repair malformed output
                  </button>
                  <button
                    className={buttonBase}
                    onClick={() => void createPlannerProposal("prompt_injection")}
                  >
                    Prompt-injection scenario
                  </button>
                  <button
                    className={buttonBase}
                    onClick={() => void createPlannerProposal("hallucinated_tool", false)}
                  >
                    Reject hallucinated tool
                  </button>
                  <button
                    className={buttonBase}
                    onClick={() => void createPlannerProposal("cyclic_plan", false)}
                  >
                    Reject cycle
                  </button>
                </div>
              </div>

              {latestPlan ? (
                <div className="mt-4 grid gap-3 lg:grid-cols-[1.2fr_0.8fr]">
                  <article className={cardClass}>
                    <div className="flex flex-wrap items-center gap-2">
                      <span className={pillClass}>plan v{latestPlan.version_number}</span>
                      <span
                        className={
                          latestPlan.status === "validated"
                            ? pillClass
                            : "rounded-full border border-rose-400/30 bg-rose-400/10 px-2 py-1 text-xs text-rose-200"
                        }
                      >
                        {latestPlan.status}
                      </span>
                    </div>
                    <p className="mt-3 text-sm text-zinc-300">{latestPlan.summary}</p>
                    {latestPlan.validation_errors.length > 0 ? (
                      <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-rose-300">
                        {latestPlan.validation_errors.map((validationError) => (
                          <li key={validationError}>{validationError}</li>
                        ))}
                      </ul>
                    ) : null}
                    <div className="mt-4 grid gap-2">
                      {latestPlan.nodes.map((node) => (
                        <div
                          className="rounded-xl border border-zinc-800 bg-black/30 p-3"
                          key={node.id}
                        >
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-mono text-xs text-violet-200">{node.key}</span>
                            <span className={mutedPillClass}>{node.kind}</span>
                            {node.tool_name ? (
                              <span className={pillClass}>
                                {node.tool_name} v{node.tool_version}
                              </span>
                            ) : null}
                          </div>
                          <p className="mt-2 text-sm font-medium text-zinc-100">{node.title}</p>
                          <p className="mt-1 text-xs text-zinc-500">{node.rationale}</p>
                        </div>
                      ))}
                    </div>
                  </article>

                  <article className={cardClass}>
                    <h4 className="font-semibold text-zinc-50">Model call evidence</h4>
                    {latestModelCall ? (
                      <div className="mt-3 grid gap-2 text-sm text-zinc-300">
                        <p>
                          Provider:{" "}
                          <span className="font-mono text-violet-200">
                            {latestModelCall.provider}
                          </span>
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
                      <div className="mt-4">
                        <p className="text-sm font-medium text-zinc-100">Plan edges</p>
                        <ol className="mt-2 grid gap-1 text-xs text-zinc-400">
                          {latestPlan.edges.map((edge) => (
                            <li key={`${edge.from}-${edge.to}`}>
                              <span className="font-mono text-violet-200">{edge.from}</span> →{" "}
                              <span className="font-mono text-violet-200">{edge.to}</span>
                            </li>
                          ))}
                        </ol>
                      </div>
                    ) : null}
                  </article>
                </div>
              ) : (
                <p className="mt-4 text-sm text-zinc-500">
                  Create a run, then generate a structured plan to inspect persisted planner
                  output.
                </p>
              )}
            </div>

            <div className="mt-4 rounded-2xl border border-zinc-800 bg-black/30 p-4">
              <h3 className="font-semibold text-zinc-50">Execution events</h3>
              <ol className="mt-3 grid gap-2 text-sm text-zinc-300">
                {events.map((event) => (
                  <li key={event.id}>
                    <span className="text-zinc-500">#{event.sequence}</span>{" "}
                    <span className="text-violet-200">{event.event_type}</span>
                  </li>
                ))}
              </ol>
            </div>

            {toolInvocations.length > 0 ? (
              <div className="mt-4 rounded-2xl border border-zinc-800 bg-black/30 p-4">
                <h3 className="font-semibold text-zinc-50">Tool invocation ledger</h3>
                <div className="mt-3 grid gap-2">
                  {toolInvocations.map((invocation) => (
                    <article
                      className="rounded-xl border border-zinc-800 bg-[#0d0d0f] p-3"
                      key={invocation.id}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="font-mono text-sm text-violet-200">
                            {invocation.tool_name} v{invocation.tool_version}
                          </p>
                          <p className="mt-1 text-xs text-zinc-500">
                            action hash {invocation.action_hash.slice(0, 16)}… · idempotency{" "}
                            {invocation.idempotency_key}
                          </p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <span className={pillClass}>{invocation.status}</span>
                          <span className={mutedPillClass}>{invocation.risk}</span>
                        </div>
                      </div>
                      {invocation.error_type ? (
                        <p className="mt-2 text-sm text-rose-300">
                          {invocation.error_type}: {invocation.error_message}
                        </p>
                      ) : null}
                    </article>
                  ))}
                </div>
              </div>
            ) : null}

            {evidenceItems.length > 0 ? (
              <div className="mt-4 rounded-2xl border border-zinc-800 bg-black/30 p-4">
                <h3 className="font-semibold text-zinc-50">Evidence provenance</h3>
                <div className="mt-3 grid gap-2">
                  {evidenceItems.map((item) => (
                    <article
                      className="rounded-xl border border-zinc-800 bg-[#0d0d0f] p-3"
                      key={item.id}
                    >
                      <div className="flex flex-wrap items-center justify-between gap-3">
                        <div>
                          <p className="font-mono text-sm text-violet-200">{item.source_name}</p>
                          <p className="mt-1 text-xs text-zinc-500">
                            {item.source_type} · content hash {item.content_hash.slice(0, 16)}…
                          </p>
                        </div>
                        <span
                          className={
                            item.trust_label === "untrusted_tool_output"
                              ? "rounded-full border border-amber-400/30 bg-amber-400/10 px-2 py-1 text-xs text-amber-200"
                              : pillClass
                          }
                        >
                          {item.trust_label}
                        </span>
                      </div>
                      <pre className="mt-3 max-h-36 overflow-auto rounded-xl border border-zinc-800 bg-black/40 p-3 text-xs text-zinc-300">
                        {JSON.stringify(item.summary, null, 2)}
                      </pre>
                    </article>
                  ))}
                </div>
              </div>
            ) : null}
          </section>
        ) : null}
      </div>
    </main>
  );
}
