import type { ActorSummary } from "@forge/shared-types";
import { Panel, Tag } from "./primitives";

export type IdentityOption<T extends string> = {
  key: T;
  label: string;
  hint: string;
};

export function IdentityBar<T extends string>({
  options,
  selected,
  actor,
  status,
  error,
  onSelect
}: {
  options: IdentityOption<T>[];
  selected: T;
  actor: ActorSummary | null;
  status: string;
  error: string | null;
  onSelect: (subject: T) => void;
}) {
  return (
    <Panel className="sticky top-4 z-20 backdrop-blur">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {options.map((option) => (
            <button
              key={option.key}
              title={option.hint}
              onClick={() => onSelect(option.key)}
              className={`rounded-md border px-3 py-1.5 text-xs font-medium transition ${
                selected === option.key
                  ? "border-accent/40 bg-accent-dim text-accent-strong"
                  : "border-line-strong bg-surface-2 text-ink-muted hover:border-ink-faint hover:text-ink"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
        {actor ? (
          <div className="flex items-center gap-2 text-xs text-ink-muted">
            <span className="font-medium text-ink">{actor.display_name}</span>
            <span className="text-ink-faint">{actor.email}</span>
            <Tag tone="accent">{actor.workspaces.length} workspace{actor.workspaces.length === 1 ? "" : "s"}</Tag>
          </div>
        ) : null}
      </div>
      <p className="mt-2.5 text-xs text-ink-faint">{status}</p>
      {error ? (
        <p className="mt-1.5 whitespace-pre-wrap rounded-md border border-rose-400/25 bg-rose-400/5 px-3 py-2 text-xs text-rose-300">
          {error}
        </p>
      ) : null}
    </Panel>
  );
}
