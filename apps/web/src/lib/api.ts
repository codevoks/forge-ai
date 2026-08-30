import type { ActorSummary, ProblemDetails } from "@forge/shared-types";

export const API_BASE_URL = process.env.NEXT_PUBLIC_FORGE_API_BASE_URL ?? "http://127.0.0.1:8000";

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
    const problem = (await response.json()) as ProblemDetails;
    throw new Error(`${problem.code}: ${problem.message}`);
  }
  return (await response.json()) as ActorSummary;
}
