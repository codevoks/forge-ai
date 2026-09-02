import type { AgentIteration } from "./api";

/** Real runtime shape of AgentIteration.counters_snapshot, observed live from the API. */
export type AgentCountersSnapshot = {
  budgets?: {
    max_iterations?: number;
    max_tool_calls?: number;
    max_model_calls?: number;
    max_context_items?: number;
    max_output_tokens?: number;
    max_invalid_decisions?: number;
    max_no_progress_decisions?: number;
  };
  evidence_items?: number;
  tool_calls_used?: number;
  model_calls_used?: number;
  invalid_decisions?: number;
  no_progress_decisions?: number;
};

export type BudgetMeterRow = {
  key: string;
  label: string;
  used: number;
  max: number;
};

/** Reads the latest iteration's counters and turns them into meter rows for the UI. */
export function budgetRowsFromIteration(iteration: AgentIteration | undefined): BudgetMeterRow[] {
  if (!iteration) return [];
  const counters = iteration.counters_snapshot as AgentCountersSnapshot;
  const budgets = counters?.budgets;
  if (!counters || !budgets) return [];

  const rows: BudgetMeterRow[] = [];
  if (budgets.max_iterations !== undefined) {
    rows.push({
      key: "iterations",
      label: "Iterations",
      used: iteration.iteration_number,
      max: budgets.max_iterations
    });
  }
  if (budgets.max_tool_calls !== undefined) {
    rows.push({
      key: "tool_calls",
      label: "Tool calls",
      used: counters.tool_calls_used ?? 0,
      max: budgets.max_tool_calls
    });
  }
  if (budgets.max_model_calls !== undefined) {
    rows.push({
      key: "model_calls",
      label: "Model calls",
      used: counters.model_calls_used ?? 0,
      max: budgets.max_model_calls
    });
  }
  if (budgets.max_invalid_decisions !== undefined) {
    rows.push({
      key: "invalid_decisions",
      label: "Invalid decisions",
      used: counters.invalid_decisions ?? 0,
      max: budgets.max_invalid_decisions
    });
  }
  if (budgets.max_no_progress_decisions !== undefined) {
    rows.push({
      key: "no_progress_decisions",
      label: "No-progress decisions",
      used: counters.no_progress_decisions ?? 0,
      max: budgets.max_no_progress_decisions
    });
  }
  return rows;
}

export function meterTone(used: number, max: number): "ok" | "warn" | "exhausted" {
  if (max <= 0) return "ok";
  const ratio = used / max;
  if (ratio >= 1) return "exhausted";
  if (ratio >= 0.75) return "warn";
  return "ok";
}
