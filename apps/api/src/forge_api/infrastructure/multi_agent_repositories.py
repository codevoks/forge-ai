import json
from typing import Any

from psycopg import Connection

from forge_api.api.errors import ProblemError
from forge_api.infrastructure.ids import uuid7


class StrategyComparisonRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def create(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        single_agent_run_id: str,
        multi_agent_run_id: str,
        objective: str,
        metrics: dict[str, Any],
        caveats: str,
        created_by: str,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            insert into strategy_comparisons
              (id, tenant_id, workspace_id, single_agent_run_id, multi_agent_run_id,
               objective, metrics, caveats, created_by)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning *
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                single_agent_run_id,
                multi_agent_run_id,
                objective,
                json.dumps(metrics),
                caveats,
                created_by,
            ),
        ).fetchone()
        assert row is not None
        return self._summary(row)

    def get_for_actor(self, *, actor_id: str, comparison_id: str) -> dict[str, Any]:
        _ = actor_id
        row = self.conn.execute(
            "select * from strategy_comparisons where id = %s",
            (comparison_id,),
        ).fetchone()
        if row is None:
            raise ProblemError(
                404, "strategy_comparison_not_found", "The strategy comparison was not found."
            )
        return self._summary(row)

    def list_for_actor(self, *, actor_id: str, workspace_id: str) -> list[dict[str, Any]]:
        _ = actor_id
        rows = self.conn.execute(
            """
            select * from strategy_comparisons
            where workspace_id = %s
            order by created_at desc
            limit 20
            """,
            (workspace_id,),
        ).fetchall()
        return [self._summary(row) for row in rows]

    def _summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "workspace_id": str(row["workspace_id"]),
            "single_agent_run_id": str(row["single_agent_run_id"]),
            "multi_agent_run_id": str(row["multi_agent_run_id"]),
            "objective": str(row["objective"]),
            "metrics": row["metrics"],
            "caveats": str(row["caveats"]),
            "created_by": str(row["created_by"]),
            "created_at": row["created_at"].isoformat(),
        }
