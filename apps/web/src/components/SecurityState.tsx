import type { ReactNode } from "react";

/**
 * A blocked/denied/exhausted outcome, presented as attempt → control → decision → consequence
 * rather than a generic red error box. A rejection here is the system working as designed.
 */
export function SecurityState({
  attempt,
  control,
  decision,
  consequence,
  detail
}: {
  attempt: string;
  control: string;
  decision: "denied" | "required" | "exhausted" | "invalid";
  consequence: string;
  detail?: ReactNode;
}) {
  const decisionLabel = {
    denied: "Denied",
    required: "Requires approval",
    exhausted: "Budget exhausted",
    invalid: "Rejected — invalid"
  }[decision];

  return (
    <div className="overflow-hidden rounded-md border border-line-strong bg-surface-2">
      <div className="grid grid-cols-1 divide-y divide-line sm:grid-cols-4 sm:divide-x sm:divide-y-0">
        <Step label="Attempt" value={attempt} />
        <Step label="Control" value={control} />
        <Step
          label="Decision"
          value={decisionLabel}
          accent="border-amber-400/40 bg-amber-400/10 text-amber-200"
        />
        <Step label="Consequence" value={consequence} />
      </div>
      {detail ? (
        <div className="border-t border-line px-4 py-3 text-xs text-ink-muted">{detail}</div>
      ) : null}
    </div>
  );
}

function Step({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="px-4 py-3">
      <p className="text-[10px] uppercase tracking-[0.14em] text-ink-faint">{label}</p>
      <p
        className={
          accent
            ? `mt-1 inline-flex rounded border px-1.5 py-0.5 text-xs font-medium ${accent}`
            : "mt-1 text-xs font-medium text-ink"
        }
      >
        {value}
      </p>
    </div>
  );
}
