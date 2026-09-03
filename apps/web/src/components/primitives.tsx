import { useRef, useState, type ReactNode } from "react";
import { copyToClipboard } from "../lib/clipboard";
import { STATE_BADGE_CLASS, STATE_LABEL, type ExecutionState } from "../lib/status";

function useCopyFeedback(value: string, resetMs = 1500) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function handleCopy() {
    const result = await copyToClipboard(value);
    setState(result);
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => setState("idle"), resetMs);
  }

  return { state, handleCopy };
}

export function Panel({
  children,
  className = "",
  padded = true
}: {
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section
      className={`rounded-lg border border-line bg-surface-1 ${padded ? "p-5" : ""} ${className}`}
    >
      {children}
    </section>
  );
}

export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-ink-faint">
      {children}
    </p>
  );
}

export function PanelHeading({
  eyebrow,
  title,
  description,
  action
}: {
  eyebrow: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <Eyebrow>{eyebrow}</Eyebrow>
        <h2 className="mt-1 text-base font-semibold tracking-tight text-ink">{title}</h2>
        {description ? <p className="mt-1.5 max-w-2xl text-sm text-ink-muted">{description}</p> : null}
      </div>
      {action ? <div className="flex flex-wrap items-center gap-2">{action}</div> : null}
    </div>
  );
}

export function StateBadge({ state, label }: { state: ExecutionState; label?: string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium tracking-wide ${STATE_BADGE_CLASS[state]}`}
    >
      {state === "active" ? (
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-current" />
        </span>
      ) : (
        <span className="inline-flex h-1.5 w-1.5 rounded-full bg-current" />
      )}
      {label ?? STATE_LABEL[state]}
    </span>
  );
}

export function Tag({
  children,
  tone = "neutral"
}: {
  children: ReactNode;
  tone?: "neutral" | "accent" | "warn" | "danger";
}) {
  const toneClass = {
    neutral: "border-line-strong bg-surface-2 text-ink-muted",
    accent: "border-accent/25 bg-accent-dim text-accent-strong",
    warn: "border-amber-400/30 bg-amber-400/10 text-amber-200",
    danger: "border-rose-400/30 bg-rose-400/10 text-rose-300"
  }[tone];
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] ${toneClass}`}>
      {children}
    </span>
  );
}

const buttonVariants = {
  primary:
    "border-transparent bg-gradient-to-b from-violet-400 to-violet-600 text-white shadow-[0_1px_0_rgba(255,255,255,0.25)_inset,0_8px_20px_-6px_rgba(139,92,246,0.55)] hover:brightness-110",
  secondary:
    "border-line-strong bg-surface-2 text-ink hover:border-ink-faint hover:bg-surface-3",
  ghost: "border-transparent bg-transparent text-ink-muted hover:bg-surface-2 hover:text-ink",
  danger:
    "border-rose-400/30 bg-rose-400/10 text-rose-200 hover:bg-rose-400/15"
};

export function Button({
  children,
  onClick,
  variant = "secondary",
  disabled = false,
  size = "md",
  title
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: keyof typeof buttonVariants;
  disabled?: boolean;
  size?: "sm" | "md";
  title?: string;
}) {
  return (
    <button
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-md border font-medium transition-all duration-100 active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40 disabled:active:scale-100 ${
        size === "sm" ? "px-2.5 py-1.5 text-xs" : "px-3.5 py-2 text-sm"
      } ${buttonVariants[variant]}`}
    >
      {children}
    </button>
  );
}

export function MetricCell({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-md border border-line bg-surface-2 px-3.5 py-3">
      <p className="text-[11px] uppercase tracking-[0.14em] text-ink-faint">{label}</p>
      <p className="mt-1.5 font-mono text-xl font-medium tabular-nums text-ink">{value}</p>
    </div>
  );
}

export function Mono({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <span className={`font-mono text-[12px] text-ink-muted ${className}`}>{children}</span>;
}

export function CopyableHash({
  value,
  length = 16,
  label
}: {
  value: string;
  length?: number;
  label?: string;
}) {
  const { state, handleCopy } = useCopyFeedback(value);
  return (
    <button
      type="button"
      onClick={() => void handleCopy()}
      title={state === "idle" ? value : undefined}
      aria-label={label ? `Copy ${label} to clipboard` : "Copy to clipboard"}
      className={`group inline-flex items-center gap-1 rounded font-mono text-[12px] transition ${
        state === "copied"
          ? "text-emerald-300"
          : state === "failed"
            ? "text-rose-300"
            : "text-ink-faint hover:text-accent-strong"
      }`}
    >
      {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : value.slice(0, length)}
      {state === "idle" ? <span className="opacity-0 transition group-hover:opacity-100">⧉</span> : null}
    </button>
  );
}

/** A small labeled copy affordance for values without a natural hash-style display (e.g. "Copy JSON"). */
export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const { state, handleCopy } = useCopyFeedback(value);
  return (
    <Button size="sm" variant="ghost" onClick={() => void handleCopy()} title={label}>
      {state === "copied" ? "Copied" : state === "failed" ? "Copy failed" : label}
    </Button>
  );
}
