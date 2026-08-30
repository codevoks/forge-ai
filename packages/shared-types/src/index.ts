import type { components } from "./generated/openapi";

export interface ProblemDetails {
  code: string;
  message: string;
  correlation_id: string;
  retryable?: boolean;
}

export type { paths, components } from "./generated/openapi";
export type TenantCreateRequest = components["schemas"]["TenantCreateRequest"];

export interface WorkspaceSummary {
  id: string;
  tenant_id: string;
  name: string;
  role: string;
  capabilities: string[];
}

export interface ActorSummary {
  user_id: string;
  external_subject: string;
  email: string;
  display_name: string;
  workspaces: WorkspaceSummary[];
}
