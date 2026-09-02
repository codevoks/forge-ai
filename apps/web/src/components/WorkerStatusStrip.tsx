import type { RecoveryScan, WorkerState } from "../lib/api";
import { Button, Panel, PanelHeading } from "./primitives";

export function WorkerStatusStrip({
  workerState,
  recovery,
  canRecover,
  onRefresh,
  onRecover
}: {
  workerState: WorkerState;
  recovery: RecoveryScan | null;
  canRecover: boolean;
  onRefresh: () => void;
  onRecover: () => void;
}) {
  const cells: { label: string; value: number; tone?: "warn" | "danger" }[] = [
    { label: "Outbox pending", value: workerState.outbox.unpublished, tone: workerState.outbox.unpublished > 0 ? "warn" : undefined },
    { label: "Outbox sent", value: workerState.outbox.published },
    { label: "Running", value: workerState.attempts.running ?? 0 },
    { label: "Checkpoints", value: workerState.checkpoints },
    { label: "Dead letters", value: workerState.dead_letters, tone: workerState.dead_letters > 0 ? "danger" : undefined }
  ];

  return (
    <Panel>
      <PanelHeading
        eyebrow="Durable worker plane"
        title="Outbox, leases, checkpoints, and recovery"
        description="PostgreSQL is authoritative; Redis is disposable coordination. Counts reflect the selected identity's workspace scope."
        action={
          <>
            <Button size="sm" onClick={onRefresh}>
              Refresh
            </Button>
            <Button size="sm" variant={canRecover ? "primary" : "secondary"} disabled={!canRecover} onClick={onRecover}>
              Run recovery scan
            </Button>
          </>
        }
      />
      <div className="mt-4 grid grid-cols-2 divide-x divide-y divide-line overflow-hidden rounded-md border border-line sm:grid-cols-5 sm:divide-y-0">
        {cells.map((cell) => (
          <div key={cell.label} className="bg-surface-2 px-3.5 py-3">
            <p className="text-[10px] uppercase tracking-[0.13em] text-ink-faint">{cell.label}</p>
            <p
              className={`mt-1 font-mono text-lg font-medium tabular-nums ${
                cell.tone === "danger"
                  ? "text-rose-300"
                  : cell.tone === "warn"
                    ? "text-amber-200"
                    : "text-ink"
              }`}
            >
              {cell.value}
            </p>
          </div>
        ))}
      </div>
      {recovery ? (
        <p className="mt-3 text-xs text-ink-muted">
          Last recovery scan — expired leases <span className="text-ink">{recovery.expired_leases}</span>, due
          retries <span className="text-ink">{recovery.due_retries}</span>, republished tasks{" "}
          <span className="text-ink">{recovery.republished_ready_tasks}</span>.
        </p>
      ) : null}
    </Panel>
  );
}
