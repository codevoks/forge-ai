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
    oidc_issuer: str = "http://forge.local/oidc"
    oidc_audience: str = "forge-local"
    oidc_jwks_path: Path = Field(default=Path("local/jwks.json"))

    def assert_zero_cost_safe(self) -> None:
        if self.external_integrations != "disabled":
            raise RuntimeError("Default Phase 1 commands require external integrations disabled.")
