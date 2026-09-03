import { useState, type ReactNode } from "react";
import { CopyButton } from "./primitives";

export type InspectorTab = {
  key: string;
  label: string;
  count?: number;
  content: ReactNode;
};

export function Inspector({ tabs, defaultTab }: { tabs: InspectorTab[]; defaultTab?: string }) {
  const [active, setActive] = useState(defaultTab ?? tabs[0]?.key);
  const current = tabs.find((t) => t.key === active) ?? tabs[0];

  if (tabs.length === 0) return null;

  return (
    <div>
      <div className="flex flex-wrap gap-1 border-b border-line pb-2">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActive(tab.key)}
            className={`rounded-md px-2.5 py-1.5 text-xs font-medium transition ${
              tab.key === current?.key
                ? "bg-surface-3 text-ink"
                : "text-ink-faint hover:bg-surface-2 hover:text-ink-muted"
            }`}
          >
            {tab.label}
            {tab.count !== undefined ? (
              <span className="ml-1.5 text-[10px] text-ink-faint">{tab.count}</span>
            ) : null}
          </button>
        ))}
      </div>
      <div className="animate-rise pt-4">{current?.content}</div>
    </div>
  );
}

/** Raw JSON is the last level of detail — collapsed by default, never the first thing shown. */
export function RawJsonDisclosure({ label, data }: { label: string; data: unknown }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-md border border-line bg-surface-2/50">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-left text-xs text-ink-faint transition hover:text-ink-muted"
      >
        <span>{label}</span>
        <span>{open ? "Hide raw JSON" : "Show raw JSON"}</span>
      </button>
      {open ? (
        <div className="border-t border-line">
          <div className="flex justify-end px-2 pt-2">
            <CopyButton value={JSON.stringify(data, null, 2)} label="Copy JSON" />
          </div>
          <pre className="max-h-72 overflow-auto px-3 pb-2.5 pt-1 font-mono text-[11px] leading-relaxed text-ink-muted">
            {JSON.stringify(data, null, 2)}
          </pre>
        </div>
      ) : null}
    </div>
  );
}
