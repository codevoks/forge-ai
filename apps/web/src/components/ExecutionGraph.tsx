import { useMemo } from "react";
import type { TaskSummary, WorkflowVersion } from "../lib/api";
import { STATE_COLOR_VAR, toExecutionState, type ExecutionState } from "../lib/status";

type LayoutNode = {
  key: string;
  name: string;
  kind: string;
  rank: number;
  slot: number;
  state: ExecutionState;
};

type LayoutEdge = {
  from: string;
  to: string;
};

const COLUMN_WIDTH = 216;
const ROW_HEIGHT = 76;
const NODE_WIDTH = 172;
const NODE_HEIGHT = 52;
const PADDING = 32;

function computeRanks(steps: WorkflowVersion["steps"], edges: WorkflowVersion["edges"]) {
  const incoming = new Map<string, string[]>();
  for (const step of steps) incoming.set(step.key, []);
  for (const edge of edges) {
    if (!incoming.has(edge.to)) incoming.set(edge.to, []);
    incoming.get(edge.to)!.push(edge.from);
  }

  const rank = new Map<string, number>();
  const resolve = (key: string, guard: Set<string>): number => {
    if (rank.has(key)) return rank.get(key)!;
    if (guard.has(key)) return 0;
    guard.add(key);
    const preds = incoming.get(key) ?? [];
    const r = preds.length === 0 ? 0 : 1 + Math.max(...preds.map((p) => resolve(p, guard)));
    rank.set(key, r);
    return r;
  };

  for (const step of steps) resolve(step.key, new Set());
  return rank;
}

export function layoutWorkflow(
  workflow: Pick<WorkflowVersion, "steps" | "edges">,
  tasks: TaskSummary[]
): { nodes: LayoutNode[]; edges: LayoutEdge[]; width: number; height: number } {
  const rank = computeRanks(workflow.steps, workflow.edges);
  const byRank = new Map<number, string[]>();
  for (const step of workflow.steps) {
    const r = rank.get(step.key) ?? 0;
    if (!byRank.has(r)) byRank.set(r, []);
    byRank.get(r)!.push(step.key);
  }

  const taskByStepKey = new Map(tasks.map((t) => [t.step_key, t]));
  const nodes: LayoutNode[] = workflow.steps.map((step) => {
    const r = rank.get(step.key) ?? 0;
    const slot = byRank.get(r)!.indexOf(step.key);
    const task = taskByStepKey.get(step.key);
    return {
      key: step.key,
      name: step.name,
      kind: step.kind,
      rank: r,
      slot,
      state: task ? toExecutionState(task.status) : "pending"
    };
  });

  const maxRank = Math.max(0, ...nodes.map((n) => n.rank));
  const maxSlot = Math.max(0, ...Array.from(byRank.values()).map((v) => v.length - 1));

  return {
    nodes,
    edges: workflow.edges,
    width: (maxRank + 1) * COLUMN_WIDTH + PADDING * 2 - (COLUMN_WIDTH - NODE_WIDTH),
    height: (maxSlot + 1) * ROW_HEIGHT + PADDING * 2 - (ROW_HEIGHT - NODE_HEIGHT)
  };
}

function nodeCenter(node: LayoutNode) {
  return {
    x: PADDING + node.rank * COLUMN_WIDTH,
    y: PADDING + node.slot * ROW_HEIGHT
  };
}

export function ExecutionGraph({
  workflow,
  tasks,
  selectedTaskId,
  onSelectTask
}: {
  workflow: Pick<WorkflowVersion, "steps" | "edges">;
  tasks: TaskSummary[];
  selectedTaskId: string | null;
  onSelectTask: (taskId: string) => void;
}) {
  const layout = useMemo(() => layoutWorkflow(workflow, tasks), [workflow, tasks]);
  const taskByStepKey = useMemo(() => new Map(tasks.map((t) => [t.step_key, t])), [tasks]);
  const nodeByKey = useMemo(() => new Map(layout.nodes.map((n) => [n.key, n])), [layout.nodes]);

  if (layout.nodes.length === 0) {
    return (
      <div className="flex h-40 items-center justify-center rounded-md border border-dashed border-line-strong text-sm text-ink-faint">
        No workflow steps to display yet.
      </div>
    );
  }

  return (
    <div className="overflow-auto rounded-md border border-line bg-surface-0/60">
      <svg
        width={layout.width}
        height={layout.height}
        viewBox={`0 0 ${layout.width} ${layout.height}`}
        className="block"
      >
        <defs>
          <marker id="graph-arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path d="M0,0 L8,4 L0,8 Z" fill="var(--color-line-strong)" />
          </marker>
        </defs>

        {layout.edges.map((edge, i) => {
          const from = nodeByKey.get(edge.from);
          const to = nodeByKey.get(edge.to);
          if (!from || !to) return null;
          const a = nodeCenter(from);
          const b = nodeCenter(to);
          const startX = a.x + NODE_WIDTH;
          const startY = a.y + NODE_HEIGHT / 2;
          const endX = b.x;
          const endY = b.y + NODE_HEIGHT / 2;
          const midX = (startX + endX) / 2;
          const fromTask = taskByStepKey.get(edge.from);
          const isFlowing = fromTask ? toExecutionState(fromTask.status) === "success" : false;

          return (
            <path
              key={`${edge.from}-${edge.to}-${i}`}
              d={`M${startX},${startY} C${midX},${startY} ${midX},${endY} ${endX},${endY}`}
              fill="none"
              stroke={isFlowing ? "var(--color-accent)" : "var(--color-line-strong)"}
              strokeWidth={isFlowing ? 2 : 1.5}
              strokeDasharray={isFlowing ? "6 4" : undefined}
              className={isFlowing ? "animate-flow" : ""}
              markerEnd="url(#graph-arrow)"
              opacity={isFlowing ? 0.9 : 0.6}
            />
          );
        })}

        {layout.nodes.map((node) => {
          const { x, y } = nodeCenter(node);
          const task = taskByStepKey.get(node.key);
          const color = STATE_COLOR_VAR[node.state];
          const selected = task ? task.id === selectedTaskId : false;
          const active = node.state === "active";

          return (
            <g
              key={node.key}
              transform={`translate(${x},${y})`}
              className="cursor-pointer"
              onClick={() => task && onSelectTask(task.id)}
            >
              <rect
                width={NODE_WIDTH}
                height={NODE_HEIGHT}
                rx={10}
                fill="var(--color-surface-2)"
                stroke={selected ? "var(--color-accent)" : color}
                strokeWidth={selected ? 2 : 1.4}
                className={active ? "animate-pulse-node" : ""}
                opacity={node.state === "pending" ? 0.55 : 1}
              />
              <circle cx={16} cy={NODE_HEIGHT / 2} r={4} fill={color} className={active ? "animate-pulse-node" : ""} />
              <text
                x={30}
                y={20}
                fill="var(--color-ink)"
                fontSize={12}
                fontWeight={500}
                className="select-none"
              >
                {node.name.length > 20 ? `${node.name.slice(0, 19)}…` : node.name}
              </text>
              <text
                x={30}
                y={36}
                fill="var(--color-ink-faint)"
                fontSize={10}
                fontFamily="var(--font-mono)"
                className="select-none"
              >
                {node.kind} · {task ? task.status : "not started"}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
