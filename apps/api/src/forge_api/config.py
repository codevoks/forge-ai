from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FORGE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql://forge_runtime:forge_runtime@localhost:55432/forge"
    migration_database_url: str = "postgresql://forge:forge@localhost:55432/forge"
    environment: Literal["development", "test", "production"] = "development"
    external_integrations: Literal["disabled", "enabled"] = "disabled"
    redis_url: str = "redis://localhost:56379/0"
    queue_stream: str = "forge:work"
    queue_group: str = "forge-workers"
    worker_id: str = "forge-worker-local"
    worker_tick_seconds: float = 1.0
    task_lease_seconds: int = 30
    task_max_attempts: int = 3
    model_provider: Literal["fake", "langchain_fake", "openai_compatible"] = "fake"
    live_model_base_url: str = "https://api.openai.com/v1"
    live_model_name: str = "gpt-4o-mini"
    live_model_api_key: str = ""
    langsmith_export_mode: Literal["local", "disabled", "enabled"] = "local"
    langsmith_endpoint: str = "https://api.smith.langchain.com"
    langsmith_api_key: str = ""
    oidc_issuer: str = "http://forge.local/oidc"
    oidc_audience: str = "forge-local"
    oidc_jwks_path: Path = Field(default=Path("local/jwks.json"))

    def assert_zero_cost_safe(self) -> None:
        if self.external_integrations != "disabled":
            raise RuntimeError("Default Forge commands require external integrations disabled.")
        if self.model_provider != "fake":
            raise RuntimeError(
                "Default Forge commands require the deterministic fake model provider."
            )
        if self.langsmith_export_mode == "enabled":
            raise RuntimeError("Default Forge commands cannot enable external LangSmith export.")
