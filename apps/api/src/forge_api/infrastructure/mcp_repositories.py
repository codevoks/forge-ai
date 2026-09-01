import json
from typing import Any

from psycopg import Connection

from forge_api.api.errors import ProblemError
from forge_api.infrastructure.ids import uuid7


class MCPServerRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def create(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        name: str,
        transport: str,
        trust_level: str,
        connection_config: dict[str, Any],
        auth_secret_reference: str | None,
        created_by: str,
    ) -> dict[str, Any]:
        existing = self.conn.execute(
            "select id from mcp_servers where tenant_id = %s and workspace_id = %s and name = %s",
            (tenant_id, workspace_id, name),
        ).fetchone()
        if existing is not None:
            raise ProblemError(
                409, "mcp_server_name_conflict", "An MCP server with this name exists."
            )
        row = self.conn.execute(
            """
            insert into mcp_servers
              (id, tenant_id, workspace_id, name, transport, trust_level, connection_config,
               auth_secret_reference, status, created_by)
            values (%s, %s, %s, %s, %s, %s, %s, %s, 'draft', %s)
            returning *
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                name,
                transport,
                trust_level,
                json.dumps(connection_config),
                auth_secret_reference,
                created_by,
            ),
        ).fetchone()
        assert row is not None
        return self._summary(row)

    def list_for_actor(self, *, actor_id: str, workspace_id: str) -> list[dict[str, Any]]:
        _ = actor_id
        rows = self.conn.execute(
            "select * from mcp_servers where workspace_id = %s order by created_at",
            (workspace_id,),
        ).fetchall()
        return [self._summary(row) for row in rows]

    def get_for_actor(self, *, actor_id: str, server_id: str) -> dict[str, Any]:
        _ = actor_id
        row = self.conn.execute("select * from mcp_servers where id = %s", (server_id,)).fetchone()
        if row is None:
            raise ProblemError(404, "mcp_server_not_found", "The MCP server was not found.")
        return self._summary(row)

    def get_for_update(self, *, server_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "select * from mcp_servers where id = %s for update", (server_id,)
        ).fetchone()
        if row is None:
            raise ProblemError(404, "mcp_server_not_found", "The MCP server was not found.")
        return self._summary(row)

    def record_health(
        self,
        *,
        server_id: str,
        status: str,
        healthy: bool,
        error: str | None,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            update mcp_servers
            set status = %s,
                last_health_checked_at = now(),
                last_health_status = %s,
                last_error = %s,
                updated_at = now()
            where id = %s
            returning *
            """,
            (status, "healthy" if healthy else "unhealthy", error, server_id),
        ).fetchone()
        assert row is not None
        return self._summary(row)

    def disable(self, *, server_id: str, expected_version: int) -> dict[str, Any]:
        row = self.conn.execute(
            """
            update mcp_servers
            set status = 'disabled', enabled = false, version = version + 1, updated_at = now()
            where id = %s and version = %s
            returning *
            """,
            (server_id, expected_version),
        ).fetchone()
        if row is None:
            raise ProblemError(409, "mcp_server_version_conflict", "MCP server version changed.")
        return self._summary(row)

    def _summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "workspace_id": str(row["workspace_id"]),
            "name": str(row["name"]),
            "transport": str(row["transport"]),
            "trust_level": str(row["trust_level"]),
            "connection_config": row["connection_config"],
            "auth_secret_reference": row["auth_secret_reference"],
            "status": str(row["status"]),
            "enabled": bool(row["enabled"]),
            "last_health_checked_at": row["last_health_checked_at"].isoformat()
            if row["last_health_checked_at"] is not None
            else None,
            "last_health_status": row["last_health_status"],
            "last_error": row["last_error"],
            "version": int(row["version"]),
            "created_at": row["created_at"].isoformat(),
        }


class MCPCapabilitySnapshotRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def create(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        server_id: str,
        protocol_version: str,
        capability_hash: str,
        tools: list[dict[str, Any]],
        created_by: str,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            insert into mcp_capability_snapshots
              (id, tenant_id, workspace_id, mcp_server_id, protocol_version, capability_hash,
               tool_count, tools, created_by)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning *
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                server_id,
                protocol_version,
                capability_hash,
                len(tools),
                json.dumps(tools),
                created_by,
            ),
        ).fetchone()
        assert row is not None
        return self._summary(row)

    def _summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "mcp_server_id": str(row["mcp_server_id"]),
            "captured_at": row["captured_at"].isoformat(),
            "protocol_version": str(row["protocol_version"]),
            "capability_hash": str(row["capability_hash"]),
            "tool_count": int(row["tool_count"]),
            "tools": row["tools"],
        }


class MCPToolMappingRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def get_by_server_and_name(
        self, *, server_id: str, remote_tool_name: str
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            "select * from mcp_tool_mappings where mcp_server_id = %s and remote_tool_name = %s",
            (server_id, remote_tool_name),
        ).fetchone()
        return self._summary(row) if row is not None else None

    def upsert_discovered(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        server_id: str,
        remote_tool_name: str,
        schema_hash: str,
        snapshot_id: str,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            insert into mcp_tool_mappings
              (id, tenant_id, workspace_id, mcp_server_id, remote_tool_name, status,
               latest_snapshot_id, schema_hash)
            values (%s, %s, %s, %s, %s, 'discovered', %s, %s)
            on conflict (mcp_server_id, remote_tool_name) do update set
              latest_snapshot_id = excluded.latest_snapshot_id,
              status = case
                when mcp_tool_mappings.status = 'disabled' then 'disabled'
                when mcp_tool_mappings.status = 'enabled'
                     and mcp_tool_mappings.schema_hash <> excluded.schema_hash then 'drifted'
                when mcp_tool_mappings.status = 'enabled' then 'enabled'
                else 'discovered'
              end,
              schema_hash = excluded.schema_hash,
              updated_at = now(),
              version = mcp_tool_mappings.version + 1
            returning *
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                server_id,
                remote_tool_name,
                snapshot_id,
                schema_hash,
            ),
        ).fetchone()
        assert row is not None
        return self._summary(row)

    def mark_missing_as_removed(
        self, *, server_id: str, seen_remote_tool_names: list[str]
    ) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            update mcp_tool_mappings
            set status = 'removed', updated_at = now(), version = version + 1
            where mcp_server_id = %s
              and status not in ('removed', 'disabled')
              and not (remote_tool_name = any(%s))
            returning *
            """,
            (server_id, seen_remote_tool_names),
        ).fetchall()
        return [self._summary(row) for row in rows]

    def list_for_server(self, *, server_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "select * from mcp_tool_mappings where mcp_server_id = %s order by remote_tool_name",
            (server_id,),
        ).fetchall()
        return [self._summary(row) for row in rows]

    def get_for_update(self, *, mapping_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "select * from mcp_tool_mappings where id = %s for update", (mapping_id,)
        ).fetchone()
        if row is None:
            raise ProblemError(404, "mcp_mapping_not_found", "The MCP tool mapping was not found.")
        return self._summary(row)

    def enable(
        self,
        *,
        mapping_id: str,
        expected_version: int,
        forge_tool_name: str,
        risk: str,
        tool_definition_id: str,
        tool_version_id: str,
        reviewed_by: str,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            update mcp_tool_mappings
            set status = 'enabled',
                forge_tool_name = %s,
                risk = %s,
                mapped_tool_definition_id = %s,
                mapped_tool_version_id = %s,
                reviewed_by = %s,
                reviewed_at = now(),
                updated_at = now(),
                version = version + 1
            where id = %s and version = %s
            returning *
            """,
            (
                forge_tool_name,
                risk,
                tool_definition_id,
                tool_version_id,
                reviewed_by,
                mapping_id,
                expected_version,
            ),
        ).fetchone()
        if row is None:
            raise ProblemError(409, "mcp_mapping_version_conflict", "MCP mapping version changed.")
        return self._summary(row)

    def disable(
        self, *, mapping_id: str, expected_version: int, reviewed_by: str
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            update mcp_tool_mappings
            set status = 'disabled', reviewed_by = %s, reviewed_at = now(),
                updated_at = now(), version = version + 1
            where id = %s and version = %s
            returning *
            """,
            (reviewed_by, mapping_id, expected_version),
        ).fetchone()
        if row is None:
            raise ProblemError(409, "mcp_mapping_version_conflict", "MCP mapping version changed.")
        return self._summary(row)

    def resolve_enabled_for_tool_name(self, *, forge_tool_name: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            select * from mcp_tool_mappings
            where forge_tool_name = %s and status = 'enabled'
            """,
            (forge_tool_name,),
        ).fetchone()
        return self._summary(row) if row is not None else None

    def _summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "workspace_id": str(row["workspace_id"]),
            "mcp_server_id": str(row["mcp_server_id"]),
            "remote_tool_name": str(row["remote_tool_name"]),
            "forge_tool_name": row["forge_tool_name"],
            "status": str(row["status"]),
            "risk": row["risk"],
            "latest_snapshot_id": str(row["latest_snapshot_id"])
            if row["latest_snapshot_id"] is not None
            else None,
            "schema_hash": str(row["schema_hash"]),
            "mapped_tool_definition_id": str(row["mapped_tool_definition_id"])
            if row["mapped_tool_definition_id"] is not None
            else None,
            "mapped_tool_version_id": str(row["mapped_tool_version_id"])
            if row["mapped_tool_version_id"] is not None
            else None,
            "reviewed_by": str(row["reviewed_by"]) if row["reviewed_by"] is not None else None,
            "reviewed_at": row["reviewed_at"].isoformat()
            if row["reviewed_at"] is not None
            else None,
            "version": int(row["version"]),
            "created_at": row["created_at"].isoformat(),
        }
