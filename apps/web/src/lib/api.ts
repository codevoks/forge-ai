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
