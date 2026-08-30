import hashlib
import json
from typing import Any

from psycopg import Connection

from forge_api.api.errors import ProblemError
from forge_api.domain.identity import ROLE_CAPABILITIES, ActorContext, Capability, Role
from forge_api.policy.authorization import AuthorizationService


def canonical_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class IdentityRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def upsert_user_from_claims(self, claims: dict[str, Any]) -> dict[str, Any]:
        subject = str(claims["sub"])
        email = str(claims.get("email", "unknown@example.invalid"))
        display_name = str(claims.get("name", email))
        row = self.conn.execute(
            """
            insert into users (external_issuer, external_subject, email, display_name)
            values (%s, %s, %s, %s)
            on conflict (external_issuer, external_subject) do update
              set email = excluded.email,
                  display_name = excluded.display_name,
                  updated_at = now(),
                  version = users.version + 1
            returning id, external_subject, email, display_name
            """,
            (str(claims["iss"]), subject, email, display_name),
        ).fetchone()
        assert row is not None
        return row

    def actor_for_user(self, user: dict[str, Any]) -> ActorContext:
        rows = self.conn.execute(
            """
            select m.tenant_id, m.workspace_id, m.role
            from memberships m
            where m.user_id = %s
            order by m.created_at
            """,
            (user["id"],),
        ).fetchall()
        return ActorContext(
            user_id=str(user["id"]),
            external_subject=str(user["external_subject"]),
            email=str(user["email"]),
            display_name=str(user["display_name"]),
            tenant_ids=frozenset(str(row["tenant_id"]) for row in rows),
            workspace_roles={str(row["workspace_id"]): Role(str(row["role"])) for row in rows},
        )


class TenantRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def create_tenant_with_workspace(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        user_id: str,
        tenant_name: str,
        workspace_name: str,
    ) -> dict[str, Any]:
        tenant = self.conn.execute(
            """
            insert into tenants (id, name)
            values (%s, %s)
            returning id, name, version
            """,
            (tenant_id, tenant_name),
        ).fetchone()
        workspace = self.conn.execute(
            """
            insert into workspaces (id, tenant_id, name)
            values (%s, %s, %s)
            returning id, tenant_id, name, version
            """,
            (workspace_id, tenant_id, workspace_name),
        ).fetchone()
        self.conn.execute(
            """
            insert into memberships (tenant_id, workspace_id, user_id, role)
            values (%s, %s, %s, %s)
            """,
            (tenant_id, workspace_id, user_id, Role.TENANT_ADMIN.value),
        )
        self.audit("tenant.created", tenant_id, user_id, {"workspace_id": workspace_id})
        return {"tenant": tenant, "workspace": workspace}

    def audit(
        self,
        event_type: str,
        tenant_id: str,
        actor_id: str,
        metadata: dict[str, Any],
    ) -> None:
        self.conn.execute(
            """
            insert into security_audit_events (tenant_id, actor_id, event_type, metadata)
            values (%s, %s, %s, %s)
            """,
            (tenant_id, actor_id, event_type, json.dumps(metadata)),
        )


class WorkspaceRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def list_for_actor(self, actor: ActorContext) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            select w.id, w.tenant_id, w.name, m.role
            from workspaces w
            join memberships m on m.workspace_id = w.id and m.tenant_id = w.tenant_id
            where m.user_id = %s
            order by w.name
            """,
            (actor.user_id,),
        ).fetchall()
        return [self._workspace_summary(row) for row in rows]

    def get_for_actor(self, actor: ActorContext, workspace_id: str) -> dict[str, Any]:
        decision = AuthorizationService().decide_workspace(
            actor, workspace_id, Capability.WORKSPACE_READ
        )
        if not decision.allowed:
            raise ProblemError(403, "workspace_forbidden", "The workspace is not accessible.")
        row = self.conn.execute(
            """
            select w.id, w.tenant_id, w.name, m.role
            from workspaces w
            join memberships m on m.workspace_id = w.id and m.tenant_id = w.tenant_id
            where w.id = %s and m.user_id = %s
            """,
            (workspace_id, actor.user_id),
        ).fetchone()
        if row is None:
            raise ProblemError(404, "workspace_not_found", "The workspace was not found.")
        return self._workspace_summary(row)

    def _workspace_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        role = Role(str(row["role"]))
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "name": str(row["name"]),
            "role": role.value,
            "capabilities": sorted(capability.value for capability in ROLE_CAPABILITIES[role]),
        }


class IdempotencyRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def existing(self, scope: str, key: str) -> dict[str, Any] | None:
        return self.conn.execute(
            """
            select request_hash, response_payload, status_code
            from idempotency_records
            where scope = %s and key = %s
            """,
            (scope, key),
        ).fetchone()

    def save(
        self,
        *,
        scope: str,
        key: str,
        request_hash: str,
        response_payload: dict[str, Any],
        status_code: int,
    ) -> None:
        self.conn.execute(
            """
            insert into idempotency_records
              (scope, key, request_hash, response_payload, status_code)
            values (%s, %s, %s, %s, %s)
            """,
            (scope, key, request_hash, json.dumps(response_payload), status_code),
        )
