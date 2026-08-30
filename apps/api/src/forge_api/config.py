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
    oidc_issuer: str = "http://forge.local/oidc"
    oidc_audience: str = "forge-local"
    oidc_jwks_path: Path = Field(default=Path("local/jwks.json"))

    def assert_zero_cost_safe(self) -> None:
        if self.external_integrations != "disabled":
            raise RuntimeError("Default Forge commands require external integrations disabled.")
