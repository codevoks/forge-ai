import { useMemo, useState } from "react";
import type { ExecutionEvent } from "../lib/api";
import { Eyebrow, Mono } from "./primitives";

type EventGroup = {
  key: string;
  eventType: string;
  taskId: string | null;
  events: ExecutionEvent[];
  firstAt: string;
  lastAt: string;
};

function groupEvents(events: ExecutionEvent[]): EventGroup[] {
  const sorted = [...events].sort((a, b) => a.sequence - b.sequence);
  const groups: EventGroup[] = [];

  for (const event of sorted) {
    const last = groups[groups.length - 1];
    if (last && last.eventType === event.event_type && last.taskId === event.task_id) {
      last.events.push(event);
      last.lastAt = event.created_at;
    } else {
      groups.push({
        key: `${event.event_type}-${event.task_id}-${event.id}`,
        eventType: event.event_type,
        taskId: event.task_id,
        events: [event],
        firstAt: event.created_at,
        lastAt: event.created_at
      });
    }
  }
  return groups;
}

const EVENT_TONE: Record<string, string> = {
  failed: "bg-[var(--color-state-failure)]",
  succeeded: "bg-[var(--color-state-success)]",
  approval: "bg-[var(--color-state-paused)]",
  rejected: "bg-[var(--color-state-failure)]",
  denied: "bg-[var(--color-state-failure)]"
};

function toneFor(eventType: string): string {
  const key = Object.keys(EVENT_TONE).find((k) => eventType.includes(k));
  return key ? EVENT_TONE[key] : "bg-[var(--color-state-ready)]";
}

export function ExecutionTimeline({ events }: { events: ExecutionEvent[] }) {
  const groups = useMemo(() => groupEvents(events), [events]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  if (groups.length === 0) {
    return <p className="text-sm text-ink-faint">No execution events recorded yet.</p>;
  }

  return (
    <div>
      <Eyebrow>{events.length} events · {groups.length} grouped entries</Eyebrow>
      <ol className="mt-3 space-y-1">
        {groups.map((group) => {
          const isOpen = expanded.has(group.key);
          const count = group.events.length;
          return (
            <li key={group.key} className="rounded-md border border-line bg-surface-2/60">
              <button
                onClick={() =>
                  setExpanded((prev) => {
                    const next = new Set(prev);
                    next.has(group.key) ? next.delete(group.key) : next.add(group.key);
                    return next;
                  })
                }
                className="flex w-full items-center gap-3 px-3 py-2 text-left transition hover:bg-surface-3/60"
              >
                <span className={`h-1.5 w-1.5 flex-shrink-0 rounded-full ${toneFor(group.eventType)}`} />
                <span className="flex-1 truncate text-xs font-medium text-ink">
                  {group.eventType.replace(/_/g, " ")}
                </span>
                {group.taskId ? (
                  <Mono className="hidden sm:inline">task {group.taskId.slice(0, 8)}</Mono>
                ) : null}
                {count > 1 ? (
                  <span className="rounded-full bg-surface-3 px-1.5 py-0.5 text-[10px] text-ink-faint">
                    ×{count}
                  </span>
                ) : null}
                <span className="text-[11px] text-ink-faint">
                  {new Date(group.lastAt).toLocaleTimeString()}
                </span>
                <span className="text-ink-faint transition-transform" style={{ transform: isOpen ? "rotate(90deg)" : undefined }}>
                  ›
                </span>
              </button>
              {isOpen ? (
                <div className="animate-rise space-y-2 border-t border-line px-3 py-2.5">
                  {group.events.map((event) => (
                    <div key={event.id} className="rounded border border-line bg-surface-0 px-2.5 py-2">
                      <div className="flex items-center justify-between text-[11px] text-ink-faint">
                        <span>seq {event.sequence}</span>
                        <span>{new Date(event.created_at).toLocaleTimeString()}</span>
                      </div>
                      <pre className="mt-1 max-h-32 overflow-auto font-mono text-[11px] text-ink-muted">
                        {JSON.stringify(event.sanitized_diff ?? event.payload, null, 2)}
                      </pre>
                    </div>
                  ))}
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
