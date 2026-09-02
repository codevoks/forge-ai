import type { ReactNode } from "react";
import type { ApprovalRequest } from "../lib/api";
import { CopyableHash, Eyebrow, Tag } from "./primitives";

const riskTone: Record<string, "neutral" | "warn" | "danger"> = {
  low: "neutral",
  medium: "warn",
  high: "danger",
  critical: "danger"
};

export function ApprovalPanel({
  approval,
  actions
}: {
  approval: ApprovalRequest;
  actions?: ReactNode;
}) {
  const decided = approval.status !== "pending";

  return (
    <div className="overflow-hidden rounded-lg border border-amber-400/25 bg-amber-400/[0.04]">
      <div className="flex items-center justify-between border-b border-amber-400/20 bg-amber-400/[0.06] px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            {!decided && (
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-amber-400 opacity-60" />
            )}
            <span className="relative inline-flex h-2 w-2 rounded-full bg-amber-400" />
          </span>
          <span className="text-xs font-semibold uppercase tracking-[0.12em] text-amber-200">
            Execution paused for approval
          </span>
        </div>
        <Tag tone={riskTone[approval.risk] ?? "warn"}>{approval.risk} risk</Tag>
      </div>

      <div className="space-y-4 px-4 py-4">
        <div>
          <Eyebrow>Why approval is required</Eyebrow>
          <p className="mt-1 text-sm text-ink">{approval.reason}</p>
        </div>

        <div>
          <Eyebrow>Action awaiting execution</Eyebrow>
          <pre className="mt-1.5 max-h-48 overflow-auto rounded-md border border-line bg-surface-0 p-3 font-mono text-[11px] leading-relaxed text-ink-muted">
            {JSON.stringify(approval.action_summary, null, 2)}
          </pre>
        </div>

        <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
          <Field label="Action hash">
            <CopyableHash value={approval.action_hash} length={10} />
          </Field>
          <Field label="Expires">{new Date(approval.expires_at).toLocaleTimeString()}</Field>
          <Field label="Requester">
            <CopyableHash value={approval.requester_id} length={8} />
          </Field>
          <Field label="Status">
            <span className="capitalize text-ink">{approval.status.replace(/_/g, " ")}</span>
          </Field>
        </div>

        {approval.decided_by ? (
          <p className="rounded-md border border-line bg-surface-2 px-3 py-2 text-xs text-ink-muted">
            Decided by <CopyableHash value={approval.decided_by} length={8} />
            {approval.decision_reason ? ` — ${approval.decision_reason}` : ""}
          </p>
        ) : null}

        {!decided && actions ? <div className="flex flex-wrap items-center gap-2 pt-1">{actions}</div> : null}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-[0.13em] text-ink-faint">{label}</p>
      <div className="mt-0.5">{children}</div>
    </div>
  );
}
