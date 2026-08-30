"use client";

import { useState } from "react";
import type { ActorSummary } from "@forge/shared-types";
import {
  advanceRun,
  cancelRun,
  createRun,
  getRun,
  getDemoToken,
  getMe,
  getWorkerState,
  listDeadLetters,
  listEvents,
  listTasks,
  listWorkflows,
  requeueDeadLetter,
  runRecoveryScan,
  type DeadLetter,
  type ExecutionEvent,
  type RecoveryScan,
  type RunSummary,
  type TaskSummary,
  type WorkerState,
  type WorkflowVersion
} from "../lib/api";

type DemoSubject = "alice" | "bob" | "mallory";

const buttonBase =
  "cursor-pointer rounded-full border border-zinc-800 bg-[#0d0d0f] px-3.5 py-2 text-sm font-medium text-zinc-100 transition duration-150 hover:-translate-y-0.5 hover:border-zinc-700 hover:bg-[#141417]";
const activeButton =
  "border-violet-400 bg-gradient-to-br from-violet-400 to-fuchsia-600 text-white shadow-[0_0_0_1px_rgba(167,139,250,0.26),0_12px_28px_rgba(147,51,234,0.28)]";
const panelClass =
  "rounded-[18px] border border-zinc-800 bg-[#0d0d0f]/90 p-4 shadow-[0_18px_60px_rgba(0,0,0,0.24)]";
const cardClass = "rounded-2xl border border-zinc-800 bg-[#141417] p-4";
const pillClass = "rounded-full border border-violet-400/25 bg-violet-400/10 px-2 py-1 text-xs text-violet-200";

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
  const [run, setRun] = useState<RunSummary | null>(null);
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const [workerState, setWorkerState] = useState<WorkerState | null>(null);
  const [deadLetters, setDeadLetters] = useState<DeadLetter[]>([]);
  const [recovery, setRecovery] = useState<RecoveryScan | null>(null);

  async function loadIdentity(subject: DemoSubject) {
    setSelected(subject);
    setError("");
    setRun(null);
    setTasks([]);
    setEvents([]);
    setWorkflows([]);
    setWorkerState(null);
    setDeadLetters([]);
    setRecovery(null);
    setStatus("Loading signed local token and workspace scope...");
    try {
      const nextToken = await getDemoToken(subject);
      const me = await getMe(nextToken);
      const workflowVersions = await listWorkflows(nextToken);
      setToken(nextToken);
      setActor(me);
      setWorkflows(workflowVersions);
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
    await refreshOperations();
  }

  async function createDeterministicRun() {
    if (!token || workflows.length === 0) {
      return;
    }
    setError("");
    setStatus("Creating persisted run and task DAG...");
    try {
      const nextRun = await createRun(token, {
        workspace_id: workflows[0].workspace_id,
        workflow_version_id: workflows[0].id,
        objective: "Demonstrate durable local worker execution."
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

  const canCreateRun = actor?.workspaces.some(
    (workspace) =>
      workspace.id === workflows[0]?.workspace_id && workspace.capabilities.includes("run.create")
  );
  const canRecover = hasCapability(actor, "run.recover");

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

        {actor && workflows.length > 0 ? (
          <section className={panelClass}>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="text-sm text-zinc-400">Published workflow version</p>
                <h2 className="mt-1 text-xl font-semibold text-zinc-50">{workflows[0].name}</h2>
                <p className="mt-2 text-sm text-zinc-400">
                  Immutable version {workflows[0].version_number}; persisted DAG with{" "}
                  {workflows[0].steps.length} steps and {workflows[0].edges.length} edges.
                </p>
              </div>
              <button
                className={`${buttonBase} ${canCreateRun ? activeButton : "opacity-50"}`}
                disabled={!canCreateRun}
                onClick={() => void createDeterministicRun()}
              >
                Create deterministic run
              </button>
            </div>

            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-4">
              {workflows[0].steps.map((step) => (
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
          </section>
        ) : null}
      </div>
    </main>
  );
}
