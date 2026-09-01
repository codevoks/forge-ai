import json
from typing import Any

from psycopg import Connection

from forge_api.domain.identity import ActorContext
from forge_api.domain.reliability import sanitize_payload
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.ids import uuid7
from forge_api.infrastructure.workflow_repositories import RunRepository


class WorkflowEngineCheckpointRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def record_checkpoint(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        run_id: str,
        task_id: str | None,
        attempt_id: str | None,
        engine_kind: str,
        engine_version: str,
        namespace: str,
        checkpoint_id: str,
        node_name: str,
        state_summary: dict[str, Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            insert into workflow_engine_checkpoints
              (id, tenant_id, workspace_id, run_id, task_id, attempt_id, engine_kind,
               engine_version, namespace, checkpoint_id, node_name, state_summary, metadata)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (tenant_id, run_id, task_id, engine_kind, namespace, checkpoint_id)
            do update set node_name = excluded.node_name,
                          state_summary = excluded.state_summary,
                          metadata = excluded.metadata
            returning *
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                run_id,
                task_id,
                attempt_id,
                engine_kind,
                engine_version,
                namespace[:120],
                checkpoint_id[:200],
                node_name[:120],
                json.dumps(sanitize_payload(state_summary)),
                json.dumps(sanitize_payload(metadata)),
            ),
        ).fetchone()
        assert row is not None
        return self._summary(row)

    def list_for_actor(self, *, actor_id: str, run_id: str) -> list[dict[str, Any]]:
        RunRepository(self.conn).get_run_for_actor(actor_id=actor_id, run_id=run_id)
        rows = self.conn.execute(
            """
            select *
            from workflow_engine_checkpoints
            where run_id = %s
            order by created_at, checkpoint_id
            """,
            (run_id,),
        ).fetchall()
        return [self._summary(row) for row in rows]

    def _summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "workspace_id": str(row["workspace_id"]),
            "run_id": str(row["run_id"]),
            "task_id": str(row["task_id"]) if row["task_id"] is not None else None,
            "attempt_id": str(row["attempt_id"]) if row["attempt_id"] is not None else None,
            "engine_kind": str(row["engine_kind"]),
            "engine_version": str(row["engine_version"]),
            "namespace": str(row["namespace"]),
            "checkpoint_id": str(row["checkpoint_id"]),
            "node_name": str(row["node_name"]),
            "state_summary": row["state_summary"],
            "metadata": row["metadata"],
            "created_at": row["created_at"].isoformat(),
        }


class WorkflowEngineService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_checkpoints(self, actor: ActorContext, run_id: str) -> list[dict[str, Any]]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return WorkflowEngineCheckpointRepository(conn).list_for_actor(
                actor_id=actor.user_id,
                run_id=run_id,
            )
