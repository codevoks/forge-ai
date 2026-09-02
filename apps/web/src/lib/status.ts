/**
 * One vocabulary for every status the product renders, so a task card, a
 * graph node, a timeline entry, and an inspector badge never disagree about
 * what "waiting_approval" looks like.
 */

export type ExecutionState =
  | "pending"
  | "ready"
  | "active"
  | "paused"
  | "success"
  | "failure"
  | "cancelled";

const RUN_OR_TASK_STATUS_TO_STATE: Record<string, ExecutionState> = {
  created: "pending",
  pending: "pending",
  ready: "ready",
  claimed: "active",
  running: "active",
  retry_wait: "paused",
  waiting_approval: "paused",
  succeeded: "success",
  failed: "failure",
  cancelled: "cancelled"
};

export function toExecutionState(status: string): ExecutionState {
  return RUN_OR_TASK_STATUS_TO_STATE[status] ?? "pending";
}

export const STATE_LABEL: Record<ExecutionState, string> = {
  pending: "Pending",
  ready: "Ready",
  active: "Running",
  paused: "Waiting",
  success: "Succeeded",
  failure: "Failed",
  cancelled: "Cancelled"
};

export const STATE_COLOR_VAR: Record<ExecutionState, string> = {
  pending: "var(--color-state-pending)",
  ready: "var(--color-state-ready)",
  active: "var(--color-state-active)",
  paused: "var(--color-state-paused)",
  success: "var(--color-state-success)",
  failure: "var(--color-state-failure)",
  cancelled: "var(--color-state-cancelled)"
};

/** Tailwind utility classes for badges/pills — text + border + tinted fill. */
export const STATE_BADGE_CLASS: Record<ExecutionState, string> = {
  pending: "border-zinc-700/60 bg-zinc-500/10 text-zinc-400",
  ready: "border-sky-400/30 bg-sky-400/10 text-sky-300",
  active: "border-violet-400/40 bg-violet-400/12 text-violet-200",
  paused: "border-amber-400/35 bg-amber-400/10 text-amber-200",
  success: "border-emerald-400/30 bg-emerald-400/10 text-emerald-300",
  failure: "border-rose-400/35 bg-rose-400/10 text-rose-300",
  cancelled: "border-zinc-600/50 bg-zinc-500/10 text-zinc-400"
};
