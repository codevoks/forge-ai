import type { AgentIteration } from "../lib/api";
import { budgetRowsFromIteration, meterTone } from "../lib/agent";
import { Eyebrow } from "./primitives";

const toneClass = {
  ok: "bg-[var(--color-state-success)]",
  warn: "bg-[var(--color-state-paused)]",
  exhausted: "bg-[var(--color-state-failure)]"
};

const toneText = {
  ok: "text-emerald-300",
  warn: "text-amber-200",
  exhausted: "text-rose-300"
};

export function AgentBudgetMeter({ iterations }: { iterations: AgentIteration[] }) {
  if (iterations.length === 0) {
    return (
      <p className="text-sm text-ink-faint">
        This task has not run as a bounded agent loop, so there is no iteration budget to show.
      </p>
    );
  }

  const latest = iterations[iterations.length - 1];
  const rows = budgetRowsFromIteration(latest);
  const terminal = ["succeeded", "failed", "cancelled"].includes(latest.decision_status);

  if (rows.length === 0) {
    return <p className="text-sm text-ink-faint">No budget counters recorded for this agent run yet.</p>;
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Eyebrow>Bounded execution room</Eyebrow>
        <span className="text-[11px] text-ink-faint">
          iteration {latest.iteration_number} · {latest.decision_status.replace(/_/g, " ")}
        </span>
      </div>
      <div className="space-y-2.5">
        {rows.map((row) => {
          const tone = meterTone(row.used, row.max);
          const pct = row.max > 0 ? Math.min(100, (row.used / row.max) * 100) : 0;
          return (
            <div key={row.key}>
              <div className="mb-1 flex items-center justify-between text-xs">
                <span className="text-ink-muted">{row.label}</span>
                <span className={`font-mono tabular-nums ${toneText[tone]}`}>
                  {row.used} / {row.max}
                </span>
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
                <div
                  className={`h-full rounded-full transition-[width] duration-300 ${toneClass[tone]}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
      {terminal ? (
        <p className="rounded-md border border-line bg-surface-2 px-3 py-2 text-xs text-ink-muted">
          {latest.decision_status === "succeeded"
            ? "Agent completed within its bounded budget — this run cannot loop forever, and it didn't need to."
            : latest.decision_status === "failed"
              ? "Agent loop terminated. This is the runtime enforcing its bound, not an unhandled crash."
              : "Agent loop was cancelled before exhausting its budget."}
        </p>
      ) : null}
    </div>
  );
}
