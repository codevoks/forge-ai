from pathlib import Path

import psycopg

from forge_api.config import Settings
from forge_api.infrastructure.dev_issuer import DevIssuer


def main() -> None:
    settings = Settings()
    settings.assert_zero_cost_safe()
    migrations_dir = Path(__file__).resolve().parents[3] / "migrations"
    with psycopg.connect(settings.migration_database_url) as conn:
        with conn.transaction():
            for migration in sorted(migrations_dir.glob("*.sql")):
                conn.execute(migration.read_text())
    DevIssuer(settings.oidc_issuer, settings.oidc_audience, settings.oidc_jwks_path).ensure_keys()
    print("Forge database migration complete.")


if __name__ == "__main__":
    main()
