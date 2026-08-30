from urllib.parse import urlparse

from forge_api.config import Settings
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.repositories import IdentityRepository, TenantRepository

TENANT_ID = "018f0000-0000-7000-8000-000000000001"
WORKSPACE_ID = "018f0000-0000-7000-8000-000000000101"


def _assert_local_database_url(database_url: str) -> None:
    parsed = urlparse(database_url)
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("The local demo seed can only reset a loopback PostgreSQL database.")


def main() -> None:
    settings = Settings()
    settings.assert_zero_cost_safe()
    _assert_local_database_url(settings.migration_database_url)
    database = Database(settings.migration_database_url)
    with database.transaction(
        tenant_id=TENANT_ID,
        actor_id="00000000-0000-0000-0000-000000000000",
    ) as conn:
        conn.execute("delete from security_audit_events")
        conn.execute("delete from idempotency_records")
        conn.execute("delete from memberships")
        conn.execute("delete from workspaces")
        conn.execute("delete from tenants")
        conn.execute("delete from users where external_issuer = %s", (settings.oidc_issuer,))

        alice = IdentityRepository(conn).upsert_user_from_claims(
            {
                "iss": settings.oidc_issuer,
                "sub": "oidc|alice",
                "email": "alice@forge.local",
                "name": "Alice Admin",
            }
        )
        bob = IdentityRepository(conn).upsert_user_from_claims(
            {
                "iss": settings.oidc_issuer,
                "sub": "oidc|bob",
                "email": "bob@forge.local",
                "name": "Bob Viewer",
            }
        )
        conn.execute(
            "insert into tenants (id, name) values (%s, %s) on conflict (id) do nothing",
            (TENANT_ID, "Forge Local Demo"),
        )
        conn.execute(
            """
            insert into workspaces (id, tenant_id, name)
            values (%s, %s, %s)
            on conflict (id) do nothing
            """,
            (WORKSPACE_ID, TENANT_ID, "Security Demo Workspace"),
        )
        conn.execute(
            """
            insert into memberships (tenant_id, workspace_id, user_id, role)
            values (%s, %s, %s, 'tenant_admin')
            on conflict (tenant_id, workspace_id, user_id) do update set role = excluded.role
            """,
            (TENANT_ID, WORKSPACE_ID, alice["id"]),
        )
        conn.execute(
            """
            insert into memberships (tenant_id, workspace_id, user_id, role)
            values (%s, %s, %s, 'viewer')
            on conflict (tenant_id, workspace_id, user_id) do update set role = excluded.role
            """,
            (TENANT_ID, WORKSPACE_ID, bob["id"]),
        )
        TenantRepository(conn).audit(
            "local.seeded",
            TENANT_ID,
            str(alice["id"]),
            {"workspace_id": WORKSPACE_ID},
        )
    print("Forge local demo data seeded.")


if __name__ == "__main__":
    main()
