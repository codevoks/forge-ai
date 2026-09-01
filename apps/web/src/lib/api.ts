import type { ActorSummary, ProblemDetails } from "@forge/shared-types";

export const API_BASE_URL = process.env.NEXT_PUBLIC_FORGE_API_BASE_URL ?? "http://127.0.0.1:8000";

export type WorkflowStep = {
  key: string;
  name: string;
  kind: string;
  input: Record<string, unknown>;
};

export type WorkflowEdge = {
  from: string;
  to: string;
};

export type WorkflowVersion = {
  id: string;
  workspace_id: string;
  name: string;
  version_number: number;
  status: string;
  steps: WorkflowStep[];
  edges: WorkflowEdge[];
};

export type RunSummary = {
  id: string;
  tenant_id: string;
  workspace_id: string;
  workflow_version_id: string;
  workflow_name: string;
  objective: string;
  status: string;
  engine_kind: "custom" | "langgraph";
  engine_version: string;
  engine_metadata: Record<string, unknown>;
  version: number;
};

export type TaskSummary = {
  id: string;
  step_key: string;
  name: string;
  kind: string;
  status: string;
  version: number;
  result: Record<string, unknown> | null;
};

export type ExecutionEvent = {
  id: string;
  event_type: string;
  sequence: number;
  aggregate_type: string;
  payload: Record<string, unknown>;
};

export type WorkerState = {
  outbox: {
    unpublished: number;
    published: number;
  };
  attempts: Record<string, number>;
  checkpoints: number;
  dead_letters: number;
};

export type DeadLetter = {
  id: string;
  tenant_id: string;
  workspace_id: string;
  run_id: string | null;
  task_id: string | null;
  message_id: string | null;
  reason: string;
  sanitized_payload: Record<string, unknown>;
  retryable: boolean;
  requeued_at: string | null;
  requeued_by: string | null;
  created_at: string;
};

export type RecoveryScan = {
  expired_leases: number;
  due_retries: number;
  republished_ready_tasks: number;
};

export type ToolSummary = {
  id: string;
  name: string;
  version: number;
  display_name: string;
  description: string;
  risk: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  status: string;
};

export type ToolInvocation = {
  id: string;
  run_id: string;
  task_id: string;
  tool_name: string;
  tool_version: number;
  status: string;
  risk: string;
  action_hash: string;
  idempotency_key: string;
  error_type: string | null;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
};

export type EvidenceItem = {
  id: string;
  run_id: string;
  task_id: string | null;
  tool_invocation_id: string | null;
  source_type: string;
  source_name: string;
  trust_label: string;
  summary: Record<string, string | number | boolean>;
  content_hash: string;
  created_at: string;
};

export type PlanNode = {
  id: string;
  key: string;
  title: string;
  kind: string;
  tool_name: string | null;
  tool_version: number | null;
  rationale: string;
  input: Record<string, unknown>;
};

export type PlanEdge = {
  from: string;
  to: string;
};

export type PlanVersion = {
  id: string;
  run_id: string;
  version_number: number;
  status: string;
  objective: string;
  summary: string;
  validation_errors: string[];
  supersedes_plan_version_id: string | null;
  nodes: PlanNode[];
  edges: PlanEdge[];
  created_at: string;
};

export type ModelCall = {
  id: string;
  run_id: string;
  provider: string;
  model_name: string;
  status: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost_minor: number;
  latency_ms: number;
  live_provider: boolean;
  error_type: string | null;
  error_message: string | null;
  created_at: string;
};

export type ApprovalRequest = {
  id: string;
  tenant_id: string;
  workspace_id: string;
  run_id: string;
  task_id: string;
  tool_invocation_id: string;
  requester_id: string;
  action_hash: string;
  binding_hash: string;
  risk: string;
  reason: string;
  action_summary: Record<string, unknown>;
  status: string;
  request_version: number;
  expires_at: string;
  decided_by: string | null;
  decided_at: string | null;
  decision_reason: string | null;
  consumed_at: string | null;
  created_at: string;
};

export type AgentIteration = {
  id: string;
  run_id: string;
  task_id: string;
  attempt_id: string;
  iteration_number: number;
  model_call_id: string;
  decision_type: string;
  decision_status: string;
  context_hash: string;
  counters_snapshot: Record<string, unknown>;
  decision: Record<string, unknown>;
  validation_errors: string[];
  result: Record<string, unknown>;
  created_at: string;
};

export type EngineCheckpoint = {
  id: string;
  run_id: string;
  task_id: string | null;
  attempt_id: string | null;
  engine_kind: string;
  engine_version: string;
  namespace: string;
  checkpoint_id: string;
  node_name: string;
  state_summary: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type EvaluationCaseResult = {
  id: string;
  evaluation_run_id: string;
  case_key: string;
  category: string;
  status: string;
  security_critical: boolean;
  provider: string;
  engine_kind: string | null;
  metrics: Record<string, unknown>;
  artifacts: Record<string, unknown>;
  failure_message: string | null;
  created_at: string;
};

export type EvaluationMetric = {
  id: string;
  evaluation_run_id: string;
  case_result_id: string | null;
  metric_name: string;
  metric_value: number;
  unit: string;
  provenance: string;
  created_at: string;
};

export type EvaluationExport = {
  id: string;
  evaluation_run_id: string;
  exporter: string;
  status: string;
  live_export: boolean;
  artifact: Record<string, unknown>;
  error_message: string | null;
  created_at: string;
};

export type EvaluationRun = {
  id: string;
  tenant_id: string;
  workspace_id: string;
  suite_id: string;
  status: string;
  provider_path: string;
  engine_matrix: string[];
  external_integrations: string;
  langsmith_export_mode: string;
  config: Record<string, unknown>;
  summary: Record<string, unknown>;
  created_by: string;
  created_at: string;
  completed_at: string | null;
  case_results: EvaluationCaseResult[];
  metrics: EvaluationMetric[];
  exports: EvaluationExport[];
};

async function parseProblem(response: Response): Promise<Error> {
  const problem = (await response.json()) as ProblemDetails;
  return new Error(`${problem.code}: ${problem.message}`);
}

export async function getDemoToken(
  subject: "alice" | "ava" | "bob" | "mallory"
): Promise<string> {
  const response = await fetch(`${API_BASE_URL}/dev/oidc/token/${subject}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Token request failed with ${response.status}`);
  }
  const payload = (await response.json()) as { access_token: string };
  return payload.access_token;
}

export async function getMe(token: string): Promise<ActorSummary> {
  const response = await fetch(`${API_BASE_URL}/v1/me`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  return (await response.json()) as ActorSummary;
}

export async function listWorkflows(token: string): Promise<WorkflowVersion[]> {
  const response = await fetch(`${API_BASE_URL}/v1/workflows`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { workflow_versions: WorkflowVersion[] };
  return payload.workflow_versions;
}

export async function createRun(
  token: string,
  input: {
    workspace_id: string;
    workflow_version_id: string;
    objective: string;
    engine_kind?: "custom" | "langgraph";
  }
): Promise<RunSummary> {
  const response = await fetch(`${API_BASE_URL}/v1/runs`, {
    method: "POST",
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "Idempotency-Key": `demo-run-${Date.now()}`
    },
    body: JSON.stringify(input)
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { run: RunSummary };
  return payload.run;
}

export async function getRun(token: string, runId: string): Promise<RunSummary> {
  const response = await fetch(`${API_BASE_URL}/v1/runs/${runId}`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { run: RunSummary };
  return payload.run;
}

export async function advanceRun(token: string, runId: string): Promise<RunSummary> {
  const response = await fetch(`${API_BASE_URL}/v1/runs/${runId}:advance`, {
    method: "POST",
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { run: RunSummary };
  return payload.run;
}

export async function cancelRun(token: string, runId: string, reason: string): Promise<RunSummary> {
  const response = await fetch(`${API_BASE_URL}/v1/runs/${runId}:cancel`, {
    method: "POST",
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ reason })
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { run: RunSummary };
  return payload.run;
}

export async function listTasks(token: string, runId: string): Promise<TaskSummary[]> {
  const response = await fetch(`${API_BASE_URL}/v1/runs/${runId}/tasks`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { tasks: TaskSummary[] };
  return payload.tasks;
}

export async function listEvents(token: string, runId: string): Promise<ExecutionEvent[]> {
  const response = await fetch(`${API_BASE_URL}/v1/runs/${runId}/events`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { events: ExecutionEvent[] };
  return payload.events;
}

export async function planRun(
  token: string,
  runId: string,
  fakeScenario: "valid" | "repairable_malformed" | "hallucinated_tool" | "cyclic_plan" | "refusal" | "prompt_injection",
  allowCorrection = true
): Promise<{ plan: PlanVersion; model_call: ModelCall; corrected: boolean; zero_cost: Record<string, unknown> }> {
  const response = await fetch(`${API_BASE_URL}/v1/runs/${runId}:plan`, {
    method: "POST",
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "Idempotency-Key": `demo-plan-${fakeScenario}-${Date.now()}`
    },
    body: JSON.stringify({
      provider: "fake",
      fake_scenario: fakeScenario,
      allow_correction: allowCorrection,
      objective_hint: "Create a bounded structured plan for this local demo run."
    })
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  return (await response.json()) as {
    plan: PlanVersion;
    model_call: ModelCall;
    corrected: boolean;
    zero_cost: Record<string, unknown>;
  };
}

export async function listPlans(token: string, runId: string): Promise<PlanVersion[]> {
  const response = await fetch(`${API_BASE_URL}/v1/runs/${runId}/plans`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { plans: PlanVersion[] };
  return payload.plans;
}

export async function listModelCalls(token: string, runId: string): Promise<ModelCall[]> {
  const response = await fetch(`${API_BASE_URL}/v1/runs/${runId}/model-calls`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { model_calls: ModelCall[] };
  return payload.model_calls;
}

export async function listApprovals(token: string): Promise<ApprovalRequest[]> {
  const response = await fetch(`${API_BASE_URL}/v1/approvals`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { approval_requests: ApprovalRequest[] };
  return payload.approval_requests;
}

export async function approveRequest(
  token: string,
  approval: ApprovalRequest,
  reason: string
): Promise<ApprovalRequest> {
  const response = await fetch(`${API_BASE_URL}/v1/approvals/${approval.id}:approve`, {
    method: "POST",
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "Idempotency-Key": `demo-approval-${approval.id}-${Date.now()}`,
      "If-Match": String(approval.request_version)
    },
    body: JSON.stringify({ reason })
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { approval_request: ApprovalRequest };
  return payload.approval_request;
}

export async function rejectRequest(
  token: string,
  approval: ApprovalRequest,
  reason: string
): Promise<ApprovalRequest> {
  const response = await fetch(`${API_BASE_URL}/v1/approvals/${approval.id}:reject`, {
    method: "POST",
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "Idempotency-Key": `demo-reject-${approval.id}-${Date.now()}`,
      "If-Match": String(approval.request_version)
    },
    body: JSON.stringify({ reason })
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { approval_request: ApprovalRequest };
  return payload.approval_request;
}

export async function getWorkerState(token: string): Promise<WorkerState> {
  const response = await fetch(`${API_BASE_URL}/v1/operations/worker-state`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { worker_state: WorkerState };
  return payload.worker_state;
}

export async function runRecoveryScan(token: string): Promise<RecoveryScan> {
  const response = await fetch(`${API_BASE_URL}/v1/operations/recovery:scan`, {
    method: "POST",
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { recovery: RecoveryScan };
  return payload.recovery;
}

export async function listDeadLetters(token: string): Promise<DeadLetter[]> {
  const response = await fetch(`${API_BASE_URL}/v1/operations/dead-letters`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { dead_letters: DeadLetter[] };
  return payload.dead_letters;
}

export async function listTools(token: string): Promise<ToolSummary[]> {
  const response = await fetch(`${API_BASE_URL}/v1/tools`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { tools: ToolSummary[] };
  return payload.tools;
}

export async function listToolInvocations(
  token: string,
  runId: string
): Promise<ToolInvocation[]> {
  const response = await fetch(`${API_BASE_URL}/v1/tools/runs/${runId}/invocations`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { tool_invocations: ToolInvocation[] };
  return payload.tool_invocations;
}

export async function listEvidence(token: string, runId: string): Promise<EvidenceItem[]> {
  const response = await fetch(`${API_BASE_URL}/v1/tools/runs/${runId}/evidence`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { evidence_items: EvidenceItem[] };
  return payload.evidence_items;
}

export async function listAgentIterations(
  token: string,
  runId: string
): Promise<AgentIteration[]> {
  const response = await fetch(`${API_BASE_URL}/v1/runs/${runId}/agent-iterations`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { agent_iterations: AgentIteration[] };
  return payload.agent_iterations;
}

export async function listEngineCheckpoints(
  token: string,
  runId: string
): Promise<EngineCheckpoint[]> {
  const response = await fetch(`${API_BASE_URL}/v1/runs/${runId}/engine-checkpoints`, {
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { engine_checkpoints: EngineCheckpoint[] };
  return payload.engine_checkpoints;
}

export async function runOfflineEvaluation(
  token: string,
  workspaceId: string
): Promise<EvaluationRun> {
  const response = await fetch(`${API_BASE_URL}/v1/evaluations`, {
    method: "POST",
    cache: "no-store",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      "Idempotency-Key": `demo-evaluation-${Date.now()}`
    },
    body: JSON.stringify({
      workspace_id: workspaceId,
      provider_path: "native_and_langchain",
      include_langgraph: true,
      langsmith_export_mode: "local"
    })
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { evaluation_run: EvaluationRun };
  return payload.evaluation_run;
}

export async function requeueDeadLetter(token: string, deadLetterId: string): Promise<RunSummary> {
  const response = await fetch(`${API_BASE_URL}/v1/operations/dead-letters/${deadLetterId}:requeue`, {
    method: "POST",
    cache: "no-store",
    headers: { Authorization: `Bearer ${token}` }
  });
  if (!response.ok) {
    throw await parseProblem(response);
  }
  const payload = (await response.json()) as { run: RunSummary };
  return payload.run;
}
