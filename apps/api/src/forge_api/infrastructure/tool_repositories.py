import json
from typing import Any

from psycopg import Connection

from forge_api.api.errors import ProblemError
from forge_api.domain.tools import (
    InvocationStatus,
    ToolRisk,
    action_hash,
    content_hash,
    registered_tools,
)
from forge_api.infrastructure.ids import uuid7


class ToolRegistryRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def sync_code_registered_tools(self) -> None:
        for tool in registered_tools():
            row = self.conn.execute(
                """
                select id from tool_definitions
                where tenant_id is null and workspace_id is null and name = %s
                """,
                (tool.name,),
            ).fetchone()
            if row is None:
                row = self.conn.execute(
                    """
                    insert into tool_definitions
                      (id, tenant_id, workspace_id, name, display_name, description, origin)
                    values (%s, null, null, %s, %s, %s, 'code')
                    returning id
                    """,
                    (str(uuid7()), tool.name, tool.display_name, tool.description),
                ).fetchone()
            else:
                self.conn.execute(
                    """
                    update tool_definitions
                    set display_name = %s, description = %s
                    where id = %s
                    """,
                    (tool.display_name, tool.description, row["id"]),
                )
            assert row is not None
            version = self.conn.execute(
                """
                select id from tool_versions
                where tool_definition_id = %s and version = %s
                """,
                (row["id"], tool.version),
            ).fetchone()
            if version is None:
                self.conn.execute(
                    """
                    insert into tool_versions
                      (id, tenant_id, workspace_id, tool_definition_id, name, version, status, risk,
                       input_schema, output_schema, timeout_ms, retryable, idempotency_required,
                       trust_label)
                    values (%s, null, null, %s, %s, %s, 'active', %s, %s, %s, %s, %s, true, %s)
                    """,
                    (
                        str(uuid7()),
                        row["id"],
                        tool.name,
                        tool.version,
                        tool.risk.value,
                        json.dumps(tool.input_schema),
                        json.dumps(tool.output_schema),
                        tool.timeout_ms,
                        tool.retryable,
                        tool.trust_label.value,
                    ),
                )
                continue
            self.conn.execute(
                """
                update tool_versions
                set status = 'active',
                    risk = %s,
                    input_schema = %s,
                    output_schema = %s,
                    timeout_ms = %s,
                    retryable = %s,
                    trust_label = %s
                where id = %s
                """,
                (
                    tool.risk.value,
                    json.dumps(tool.input_schema),
                    json.dumps(tool.output_schema),
                    tool.timeout_ms,
                    tool.retryable,
                    tool.trust_label.value,
                    version["id"],
                ),
            )

    def list_for_actor(self, *, actor_id: str) -> list[dict[str, Any]]:
        _ = actor_id
        rows = self.conn.execute(
            """
            select tv.id, tv.name, tv.version, td.display_name, td.description, td.origin,
                   tv.status, tv.risk, tv.input_schema, tv.output_schema,
                   tv.timeout_ms, tv.retryable, tv.trust_label,
                   mm.mcp_server_id, mm.remote_tool_name
            from tool_versions tv
            join tool_definitions td on td.id = tv.tool_definition_id
            left join mcp_tool_mappings mm on mm.mapped_tool_version_id = tv.id
            where tv.status = 'active'
            order by tv.name, tv.version
            """
        ).fetchall()
        return [self._summary(row) for row in rows]

    def resolve(self, *, name: str, version: int) -> dict[str, Any]:
        row = self.conn.execute(
            """
            select tv.id, tv.name, tv.version, td.display_name, td.description, td.origin,
                   tv.status, tv.risk, tv.input_schema, tv.output_schema,
                   tv.timeout_ms, tv.retryable, tv.trust_label,
                   mm.mcp_server_id, mm.remote_tool_name
            from tool_versions tv
            join tool_definitions td on td.id = tv.tool_definition_id
            left join mcp_tool_mappings mm on mm.mapped_tool_version_id = tv.id
            where tv.name = %s and tv.version = %s and tv.status = 'active'
            """,
            (name, version),
        ).fetchone()
        if row is None:
            raise ProblemError(404, "tool_not_found", "The requested tool version was not found.")
        return self._summary(row)

    def try_resolve(self, *, name: str, version: int) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            select tv.id, tv.name, tv.version, td.display_name, td.description, td.origin,
                   tv.status, tv.risk, tv.input_schema, tv.output_schema,
                   tv.timeout_ms, tv.retryable, tv.trust_label,
                   mm.mcp_server_id, mm.remote_tool_name
            from tool_versions tv
            join tool_definitions td on td.id = tv.tool_definition_id
            left join mcp_tool_mappings mm on mm.mapped_tool_version_id = tv.id
            where tv.name = %s and tv.version = %s and tv.status = 'active'
            """,
            (name, version),
        ).fetchone()
        return self._summary(row) if row is not None else None

    def upsert_mcp_tool_definition(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        name: str,
        display_name: str,
        description: str,
    ) -> str:
        row = self.conn.execute(
            """
            select id from tool_definitions
            where tenant_id = %s and workspace_id = %s and name = %s
            """,
            (tenant_id, workspace_id, name),
        ).fetchone()
        if row is None:
            row = self.conn.execute(
                """
                insert into tool_definitions
                  (id, tenant_id, workspace_id, name, display_name, description, origin)
                values (%s, %s, %s, %s, %s, %s, 'mcp')
                returning id
                """,
                (str(uuid7()), tenant_id, workspace_id, name, display_name, description),
            ).fetchone()
        else:
            self.conn.execute(
                "update tool_definitions set display_name = %s, description = %s where id = %s",
                (display_name, description, row["id"]),
            )
        assert row is not None
        return str(row["id"])

    def next_version_number(self, *, tool_definition_id: str) -> int:
        row = self.conn.execute(
            "select coalesce(max(version), 0) + 1 as next_version from tool_versions "
            "where tool_definition_id = %s",
            (tool_definition_id,),
        ).fetchone()
        assert row is not None
        return int(row["next_version"])

    def insert_mcp_tool_version(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        tool_definition_id: str,
        name: str,
        version: int,
        risk: str,
        input_schema: dict[str, Any],
        output_schema: dict[str, Any],
        timeout_ms: int,
        retryable: bool,
    ) -> str:
        row = self.conn.execute(
            """
            insert into tool_versions
              (id, tenant_id, workspace_id, tool_definition_id, name, version, status, risk,
               input_schema, output_schema, timeout_ms, retryable, idempotency_required,
               trust_label)
            values (%s, %s, %s, %s, %s, %s, 'active', %s, %s, %s, %s, %s, true,
                    'untrusted_tool_output')
            returning id
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                tool_definition_id,
                name,
                version,
                risk,
                json.dumps(input_schema),
                json.dumps(output_schema),
                timeout_ms,
                retryable,
            ),
        ).fetchone()
        assert row is not None
        return str(row["id"])

    def retire(self, *, tool_version_id: str) -> None:
        self.conn.execute(
            "update tool_versions set status = 'retired' where id = %s", (tool_version_id,)
        )

    def _summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "version": int(row["version"]),
            "display_name": str(row["display_name"]),
            "description": str(row["description"]),
            "origin": str(row["origin"]),
            "status": str(row["status"]),
            "risk": str(row["risk"]),
            "input_schema": row["input_schema"],
            "output_schema": row["output_schema"],
            "timeout_ms": int(row["timeout_ms"]),
            "retryable": bool(row["retryable"]),
            "trust_label": str(row["trust_label"]),
            "mcp_server_id": str(row["mcp_server_id"])
            if row.get("mcp_server_id") is not None
            else None,
            "mcp_remote_tool_name": str(row["remote_tool_name"])
            if row.get("remote_tool_name") is not None
            else None,
        }


class RunToolGrantRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def grant_tools_for_run(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        run_id: str,
        actor_id: str,
        workflow_version: dict[str, Any],
    ) -> None:
        registry = ToolRegistryRepository(self.conn)
        for step in workflow_version["steps"]:
            for tool_name, tool_version in tool_references_from_step(step):
                tool = registry.resolve(name=tool_name, version=tool_version)
                self.conn.execute(
                    """
                    insert into run_tool_grants
                      (id, tenant_id, workspace_id, run_id, tool_version_id, tool_name,
                       tool_version, risk, granted_by)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    on conflict (run_id, tool_version_id) do nothing
                    """,
                    (
                        str(uuid7()),
                        tenant_id,
                        workspace_id,
                        run_id,
                        tool["id"],
                        tool["name"],
                        tool["version"],
                        tool["risk"],
                        actor_id,
                    ),
                )

    def require_grant(
        self,
        *,
        run_id: str,
        tool_name: str,
        tool_version: int,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            select g.id, g.tenant_id, g.workspace_id, g.run_id, g.tool_version_id,
                   g.tool_name, g.tool_version, g.risk
            from run_tool_grants g
            where g.run_id = %s and g.tool_name = %s and g.tool_version = %s
            """,
            (run_id, tool_name, tool_version),
        ).fetchone()
        if row is None:
            raise ProblemError(
                403,
                "tool_not_granted",
                "The run is not granted this exact tool version.",
            )
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "workspace_id": str(row["workspace_id"]),
            "run_id": str(row["run_id"]),
            "tool_version_id": str(row["tool_version_id"]),
            "tool_name": str(row["tool_name"]),
            "tool_version": int(row["tool_version"]),
            "risk": str(row["risk"]),
        }


class ToolInvocationRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def begin_intent(
        self,
        *,
        claim: dict[str, Any],
        tool: dict[str, Any],
        risk: ToolRisk,
        arguments: dict[str, Any],
        mcp_server_id: str | None = None,
        mcp_provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        computed_hash = action_hash(str(tool["name"]), int(tool["version"]), arguments)
        idempotency_key = (
            f"tenant:{claim['tenant_id']}:run:{claim['run_id']}:task:{claim['task_id']}:"
            f"tool:{tool['id']}:action:{computed_hash}"
        )
        inserted = self.conn.execute(
            """
            insert into tool_invocations
              (id, tenant_id, workspace_id, run_id, task_id, attempt_id, tool_version_id,
               tool_name, tool_version, risk, action_hash, idempotency_key, status, input,
               mcp_server_id, mcp_provenance)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'intent_recorded', %s, %s, %s)
            on conflict (tenant_id, workspace_id, run_id, task_id, tool_version_id, action_hash)
            do nothing
            returning *
            """,
            (
                str(uuid7()),
                claim["tenant_id"],
                claim["workspace_id"],
                claim["run_id"],
                claim["task_id"],
                claim["attempt_id"],
                tool["id"],
                tool["name"],
                tool["version"],
                risk.value,
                computed_hash,
                idempotency_key,
                json.dumps(arguments),
                mcp_server_id,
                json.dumps(mcp_provenance) if mcp_provenance is not None else None,
            ),
        ).fetchone()
        if inserted is not None:
            return self._summary(inserted)
        existing = self.conn.execute(
            """
            select * from tool_invocations
            where tenant_id = %s and workspace_id = %s and run_id = %s and task_id = %s
              and tool_version_id = %s and action_hash = %s
            """,
            (
                claim["tenant_id"],
                claim["workspace_id"],
                claim["run_id"],
                claim["task_id"],
                tool["id"],
                computed_hash,
            ),
        ).fetchone()
        assert existing is not None
        return self._summary(existing)

    def mark_executing(self, *, invocation_id: str) -> None:
        self.conn.execute(
            """
            update tool_invocations
            set status = 'executing', started_at = coalesce(started_at, now()), updated_at = now()
            where id = %s and status in ('intent_recorded', 'authorized', 'failed')
            """,
            (invocation_id,),
        )

    def mark_authorized(self, *, invocation_id: str) -> None:
        self.conn.execute(
            """
            update tool_invocations
            set status = 'authorized', updated_at = now()
            where id = %s and status = 'approval_required'
            """,
            (invocation_id,),
        )

    def mark_succeeded(
        self,
        *,
        invocation_id: str,
        output: dict[str, Any],
        provider_operation_id: str | None,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            update tool_invocations
            set status = 'succeeded',
                output = %s,
                provider_operation_id = %s,
                completed_at = now(),
                updated_at = now()
            where id = %s
            returning *
            """,
            (json.dumps(output), provider_operation_id, invocation_id),
        ).fetchone()
        assert row is not None
        return self._summary(row)

    def mark_failed(
        self,
        *,
        invocation_id: str,
        status: InvocationStatus,
        error_type: str,
        error_message: str,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            update tool_invocations
            set status = %s,
                error_type = %s,
                error_message = %s,
                completed_at = now(),
                updated_at = now()
            where id = %s
            returning *
            """,
            (status.value, error_type, error_message[:500], invocation_id),
        ).fetchone()
        assert row is not None
        return self._summary(row)

    def add_evidence(
        self,
        *,
        claim: dict[str, Any],
        invocation_id: str,
        source_name: str,
        trust_label: str,
        output: dict[str, Any],
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            insert into evidence_items
              (id, tenant_id, workspace_id, run_id, task_id, tool_invocation_id,
               source_type, source_name, trust_label, content_hash, summary)
            values (%s, %s, %s, %s, %s, %s, 'tool_output', %s, %s, %s, %s)
            returning *
            """,
            (
                str(uuid7()),
                claim["tenant_id"],
                claim["workspace_id"],
                claim["run_id"],
                claim["task_id"],
                invocation_id,
                source_name,
                trust_label,
                content_hash(output),
                json.dumps(output),
            ),
        ).fetchone()
        assert row is not None
        return {
            "id": str(row["id"]),
            "trust_label": str(row["trust_label"]),
            "content_hash": str(row["content_hash"]),
            "source_name": str(row["source_name"]),
        }

    def list_invocations_for_actor(self, *, actor_id: str, run_id: str) -> list[dict[str, Any]]:
        _ = actor_id
        rows = self.conn.execute(
            """
            select * from tool_invocations
            where run_id = %s
            order by created_at
            """,
            (run_id,),
        ).fetchall()
        return [self._summary(row) for row in rows]

    def list_evidence_for_actor(self, *, actor_id: str, run_id: str) -> list[dict[str, Any]]:
        _ = actor_id
        rows = self.conn.execute(
            """
            select id, run_id, task_id, tool_invocation_id, source_type, source_name,
                   trust_label, content_hash, summary, retention_policy, created_at
            from evidence_items
            where run_id = %s
            order by created_at
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "run_id": str(row["run_id"]),
                "task_id": str(row["task_id"]) if row["task_id"] is not None else None,
                "tool_invocation_id": str(row["tool_invocation_id"])
                if row["tool_invocation_id"] is not None
                else None,
                "source_type": str(row["source_type"]),
                "source_name": str(row["source_name"]),
                "trust_label": str(row["trust_label"]),
                "content_hash": str(row["content_hash"]),
                "summary": row["summary"],
                "retention_policy": str(row["retention_policy"]),
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]

    def _summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "workspace_id": str(row["workspace_id"]),
            "run_id": str(row["run_id"]),
            "task_id": str(row["task_id"]),
            "attempt_id": str(row["attempt_id"]) if row["attempt_id"] is not None else None,
            "tool_version_id": str(row["tool_version_id"]),
            "tool_name": str(row["tool_name"]),
            "tool_version": int(row["tool_version"]),
            "risk": str(row["risk"]),
            "action_hash": str(row["action_hash"]),
            "idempotency_key": str(row["idempotency_key"]),
            "status": str(row["status"]),
            "input": row["input"],
            "output": row["output"],
            "error_type": str(row["error_type"]) if row["error_type"] is not None else None,
            "error_message": str(row["error_message"])
            if row["error_message"] is not None
            else None,
            "mcp_server_id": str(row["mcp_server_id"])
            if row.get("mcp_server_id") is not None
            else None,
            "mcp_provenance": row.get("mcp_provenance"),
            "provider_operation_id": str(row["provider_operation_id"])
            if row["provider_operation_id"] is not None
            else None,
            "created_at": row["created_at"].isoformat(),
            "completed_at": row["completed_at"].isoformat()
            if row["completed_at"] is not None
            else None,
        }


def tool_reference_from_step(step_input: dict[str, Any]) -> tuple[str, int]:
    try:
        tool_name = str(step_input["tool_name"])
        tool_version = int(step_input["tool_version"])
        arguments = step_input["arguments"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ProblemError(
            422,
            "tool_step_invalid",
            "Tool steps require tool_name, tool_version, and arguments.",
        ) from exc
    if not isinstance(arguments, dict):
        raise ProblemError(422, "tool_step_invalid", "Tool arguments must be an object.")
    return tool_name, tool_version


def tool_references_from_step(step: dict[str, Any]) -> list[tuple[str, int]]:
    if step["kind"] == "tool":
        return [tool_reference_from_step(step["input"])]
    if step["kind"] != "agent":
        return []
    step_input = step["input"]
    if not isinstance(step_input, dict):
        raise ProblemError(422, "agent_task_invalid", "Agent step input must be an object.")
    allowed_tools = step_input.get("allowed_tools", [])
    if not isinstance(allowed_tools, list):
        raise ProblemError(422, "agent_task_invalid", "Agent allowed_tools must be a list.")
    references: list[tuple[str, int]] = []
    for item in allowed_tools:
        if not isinstance(item, dict):
            raise ProblemError(422, "agent_task_invalid", "Agent tool grant must be an object.")
        try:
            references.append((str(item["tool_name"]), int(item["tool_version"])))
        except (KeyError, TypeError, ValueError) as exc:
            raise ProblemError(
                422,
                "agent_task_invalid",
                "Agent tool grants require tool_name and tool_version.",
            ) from exc
    return references
