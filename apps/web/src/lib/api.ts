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

async function parseProblem(response: Response): Promise<Error> {
  const problem = (await response.json()) as ProblemDetails;
  return new Error(`${problem.code}: ${problem.message}`);
}

export async function getDemoToken(subject: "alice" | "bob" | "mallory"): Promise<string> {
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
  input: { workspace_id: string; workflow_version_id: string; objective: string }
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
