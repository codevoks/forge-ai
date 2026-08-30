export type ExternalIntegrationMode = "disabled" | "enabled";

export interface PublicForgeConfig {
  apiBaseUrl: string;
  externalIntegrations: ExternalIntegrationMode;
}

export function readPublicForgeConfig(): PublicForgeConfig {
  const externalIntegrations =
    process.env.FORGE_EXTERNAL_INTEGRATIONS === "enabled" ? "enabled" : "disabled";

  return {
    apiBaseUrl: process.env.NEXT_PUBLIC_FORGE_API_BASE_URL ?? "http://127.0.0.1:8000",
    externalIntegrations
  };
}
