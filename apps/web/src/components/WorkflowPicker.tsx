import type { WorkflowVersion } from "../lib/api";
import { ExecutionGraph } from "./ExecutionGraph";
import { Button, Panel, PanelHeading, Tag } from "./primitives";

type EngineKind = "custom" | "langgraph";

export function WorkflowPicker({
  workflows,
  selectedWorkflow,
  selectedWorkflowId,
  selectedEngine,
  canCreateRun,
  onSelectWorkflow,
  onSelectEngine,
  onCreateRun
}: {
  workflows: WorkflowVersion[];
  selectedWorkflow: WorkflowVersion | undefined;
  selectedWorkflowId: string;
  selectedEngine: EngineKind;
  canCreateRun: boolean;
  onSelectWorkflow: (workflowId: string) => void;
  onSelectEngine: (engine: EngineKind) => void;
  onCreateRun: () => void;
}) {
  if (!selectedWorkflow) return null;

  return (
    <Panel>
      <PanelHeading
        eyebrow="Published workflow version"
        title={selectedWorkflow.name}
        description={`Immutable version ${selectedWorkflow.version_number} — a persisted DAG with ${selectedWorkflow.steps.length} steps and ${selectedWorkflow.edges.length} edges.`}
        action={
          <Button variant="primary" disabled={!canCreateRun} onClick={onCreateRun}>
            Run this workflow
          </Button>
        }
      />

      <div className="mt-4 flex flex-wrap gap-1.5">
        {workflows.map((workflow) => (
          <button
            key={workflow.id}
            onClick={() => onSelectWorkflow(workflow.id)}
            className={`rounded-md border px-2.5 py-1.5 text-xs font-medium transition ${
              selectedWorkflowId === workflow.id
                ? "border-accent/40 bg-accent-dim text-accent-strong"
                : "border-line-strong bg-surface-2 text-ink-muted hover:text-ink"
            }`}
          >
            {workflow.name}
          </button>
        ))}
      </div>

      <div className="mt-4">
        <ExecutionGraph workflow={selectedWorkflow} tasks={[]} selectedTaskId={null} onSelectTask={() => {}} />
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-md border border-accent/20 bg-accent-dim/40 px-4 py-3">
        <div>
          <p className="text-xs font-medium text-ink">Custom runtime or LangGraph StateGraph — same Forge authority</p>
          <p className="mt-1 text-xs text-ink-muted">
            The engine is selected per run for comparison. PostgreSQL, policy, tools, approvals, budgets, and
            evidence stay enforced by Forge application code either way.
          </p>
        </div>
        <div className="flex gap-1.5">
          <button
            onClick={() => onSelectEngine("custom")}
            className={`rounded-md border px-2.5 py-1.5 text-xs font-medium transition ${
              selectedEngine === "custom"
                ? "border-accent/40 bg-surface-1 text-accent-strong"
                : "border-line-strong bg-surface-2 text-ink-muted hover:text-ink"
            }`}
          >
            Custom engine
          </button>
          <button
            onClick={() => onSelectEngine("langgraph")}
            className={`rounded-md border px-2.5 py-1.5 text-xs font-medium transition ${
              selectedEngine === "langgraph"
                ? "border-accent/40 bg-surface-1 text-accent-strong"
                : "border-line-strong bg-surface-2 text-ink-muted hover:text-ink"
            }`}
          >
            LangGraph engine
          </button>
        </div>
      </div>
      {!canCreateRun ? (
        <p className="mt-2 text-xs text-ink-faint">
          <Tag>run.create</Tag> capability required for the current identity to start a run.
        </p>
      ) : null}
    </Panel>
  );
}
