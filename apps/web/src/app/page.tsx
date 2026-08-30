"use client";

import { useState } from "react";
import type { ActorSummary } from "@forge/shared-types";
import {
  advanceRun,
  createRun,
  getDemoToken,
  getMe,
  listEvents,
  listTasks,
  listWorkflows,
  type ExecutionEvent,
  type RunSummary,
  type TaskSummary,
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

  async function loadIdentity(subject: DemoSubject) {
    setSelected(subject);
    setError("");
    setRun(null);
    setTasks([]);
    setEvents([]);
    setWorkflows([]);
    setStatus("Loading signed local token and workspace scope...");
    try {
      const nextToken = await getDemoToken(subject);
      const me = await getMe(nextToken);
      const workflowVersions = await listWorkflows(nextToken);
      setToken(nextToken);
      setActor(me);
      setWorkflows(workflowVersions);
      setStatus("Authenticated through the local OIDC/JWKS path.");
    } catch (caught) {
      setActor(null);
      setToken("");
      setError(caught instanceof Error ? caught.message : "Unknown error");
      setStatus("Identity request failed safely.");
    }
  }

  async function refreshRunState(nextRun: RunSummary) {
    setRun(nextRun);
    const [nextTasks, nextEvents] = await Promise.all([
      listTasks(token, nextRun.id),
      listEvents(token, nextRun.id)
    ]);
    setTasks(nextTasks);
    setEvents(nextEvents);
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
        objective: "Demonstrate deterministic Phase 2 workflow execution."
      });
      await refreshRunState(nextRun);
      setStatus("Run created. Root tasks are ready based on dependency evaluation.");
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
      await refreshRunState(nextRun);
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

  const canCreateRun = actor?.workspaces.some(
    (workspace) =>
      workspace.id === workflows[0]?.workspace_id && workspace.capabilities.includes("run.create")
  );

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_20%_0%,rgba(167,139,250,0.16),transparent_32rem),linear-gradient(180deg,#09090b_0%,#050505_44%)] px-6 py-8">
      <div className="mx-auto grid max-w-5xl gap-4">
        <section>
          <p className="text-sm text-zinc-400">Forge AI control plane</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-zinc-50">
            Identity, tenancy, and deterministic workflow execution
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
              <button
                className={`${buttonBase} ${run.status === "running" ? activeButton : "opacity-50"}`}
                disabled={run.status !== "running"}
                onClick={() => void advanceDeterministicRun()}
              >
                Advance one ready task
              </button>
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
