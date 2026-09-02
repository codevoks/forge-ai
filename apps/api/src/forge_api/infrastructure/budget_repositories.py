from datetime import date
from typing import Any

from psycopg import Connection

from forge_api.api.errors import ProblemError
from forge_api.domain.budgets import (
    DEFAULT_MAX_CURRENCY_MINOR_PER_DAY,
    DEFAULT_MAX_REQUESTS_PER_DAY,
    DEFAULT_MAX_TOKENS_PER_DAY,
)
from forge_api.infrastructure.ids import uuid7


class BudgetPolicyRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def get_workspace_policy(
        self, *, tenant_id: str, workspace_id: str
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            "select * from budget_policies "
            "where tenant_id = %s and workspace_id = %s and scope = 'workspace'",
            (tenant_id, workspace_id),
        ).fetchone()
        return self._summary(row) if row is not None else None

    def get_or_create_workspace_policy(
        self, *, tenant_id: str, workspace_id: str, created_by: str
    ) -> dict[str, Any]:
        existing = self.get_workspace_policy(tenant_id=tenant_id, workspace_id=workspace_id)
        if existing is not None:
            return existing
        row = self.conn.execute(
            """
            insert into budget_policies
              (id, tenant_id, workspace_id, scope, max_requests_per_day, max_tokens_per_day,
               max_currency_minor_per_day, created_by)
            values (%s, %s, %s, 'workspace', %s, %s, %s, %s)
            on conflict (tenant_id, workspace_id, scope) do update set scope = excluded.scope
            returning *
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                DEFAULT_MAX_REQUESTS_PER_DAY,
                DEFAULT_MAX_TOKENS_PER_DAY,
                DEFAULT_MAX_CURRENCY_MINOR_PER_DAY,
                created_by,
            ),
        ).fetchone()
        assert row is not None
        return self._summary(row)

    def set_workspace_policy(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        max_requests_per_day: int,
        max_tokens_per_day: int,
        max_currency_minor_per_day: int,
        created_by: str,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            insert into budget_policies
              (id, tenant_id, workspace_id, scope, max_requests_per_day, max_tokens_per_day,
               max_currency_minor_per_day, created_by)
            values (%s, %s, %s, 'workspace', %s, %s, %s, %s)
            on conflict (tenant_id, workspace_id, scope) do update set
              max_requests_per_day = excluded.max_requests_per_day,
              max_tokens_per_day = excluded.max_tokens_per_day,
              max_currency_minor_per_day = excluded.max_currency_minor_per_day,
              rate_card_version = budget_policies.rate_card_version + 1
            returning *
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                max_requests_per_day,
                max_tokens_per_day,
                max_currency_minor_per_day,
                created_by,
            ),
        ).fetchone()
        assert row is not None
        return self._summary(row)

    def _summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "workspace_id": str(row["workspace_id"]) if row["workspace_id"] else None,
            "scope": str(row["scope"]),
            "max_requests_per_day": int(row["max_requests_per_day"]),
            "max_tokens_per_day": int(row["max_tokens_per_day"]),
            "max_currency_minor_per_day": int(row["max_currency_minor_per_day"]),
            "rate_card_version": int(row["rate_card_version"]),
            "created_at": row["created_at"].isoformat(),
        }


class BudgetUsageRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def try_reserve(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        usage_date: date,
        requests: int,
        tokens: int,
        currency_minor: int,
        max_requests: int,
        max_tokens: int,
        max_currency_minor: int,
    ) -> bool:
        self.conn.execute(
            """
            insert into budget_usage_daily (id, tenant_id, workspace_id, usage_date)
            values (%s, %s, %s, %s)
            on conflict (tenant_id, workspace_id, usage_date) do nothing
            """,
            (str(uuid7()), tenant_id, workspace_id, usage_date),
        )
        row = self.conn.execute(
            """
            update budget_usage_daily
            set requests_used = requests_used + %s,
                tokens_used = tokens_used + %s,
                currency_minor_used = currency_minor_used + %s,
                updated_at = now()
            where tenant_id = %s and workspace_id = %s and usage_date = %s
              and requests_used + %s <= %s
              and tokens_used + %s <= %s
              and currency_minor_used + %s <= %s
            returning id
            """,
            (
                requests,
                tokens,
                currency_minor,
                tenant_id,
                workspace_id,
                usage_date,
                requests,
                max_requests,
                tokens,
                max_tokens,
                currency_minor,
                max_currency_minor,
            ),
        ).fetchone()
        return row is not None

    def adjust(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        usage_date: date,
        delta_requests: int,
        delta_tokens: int,
        delta_currency_minor: int,
    ) -> None:
        self.conn.execute(
            """
            update budget_usage_daily
            set requests_used = greatest(0, requests_used + %s),
                tokens_used = greatest(0, tokens_used + %s),
                currency_minor_used = greatest(0, currency_minor_used + %s),
                updated_at = now()
            where tenant_id = %s and workspace_id = %s and usage_date = %s
            """,
            (
                delta_requests,
                delta_tokens,
                delta_currency_minor,
                tenant_id,
                workspace_id,
                usage_date,
            ),
        )

    def get_for_actor(
        self, *, tenant_id: str, workspace_id: str, usage_date: date
    ) -> dict[str, Any]:
        row = self.conn.execute(
            "select * from budget_usage_daily "
            "where tenant_id = %s and workspace_id = %s and usage_date = %s",
            (tenant_id, workspace_id, usage_date),
        ).fetchone()
        if row is None:
            return {
                "requests_used": 0,
                "tokens_used": 0,
                "currency_minor_used": 0,
                "usage_date": usage_date.isoformat(),
            }
        return {
            "requests_used": int(row["requests_used"]),
            "tokens_used": int(row["tokens_used"]),
            "currency_minor_used": int(row["currency_minor_used"]),
            "usage_date": row["usage_date"].isoformat(),
        }


class BudgetReservationRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def create(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        run_id: str | None,
        task_id: str | None,
        operation: str,
        estimated_requests: int,
        estimated_tokens: int,
        estimated_currency_minor: int,
        usage_date: date,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            insert into budget_reservations
              (id, tenant_id, workspace_id, run_id, task_id, operation, status,
               estimated_requests, estimated_tokens, estimated_currency_minor, usage_date)
            values (%s, %s, %s, %s, %s, %s, 'reserved', %s, %s, %s, %s)
            returning *
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                run_id,
                task_id,
                operation,
                estimated_requests,
                estimated_tokens,
                estimated_currency_minor,
                usage_date,
            ),
        ).fetchone()
        assert row is not None
        return self._summary(row)

    def get_for_update(self, *, reservation_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "select * from budget_reservations where id = %s for update",
            (reservation_id,),
        ).fetchone()
        if row is None:
            raise ProblemError(
                404, "budget_reservation_not_found", "The budget reservation was not found."
            )
        return self._summary(row)

    def settle(
        self,
        *,
        reservation_id: str,
        actual_requests: int,
        actual_tokens: int,
        actual_currency_minor: int,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            update budget_reservations
            set status = 'settled', actual_requests = %s, actual_tokens = %s,
                actual_currency_minor = %s, settled_at = now()
            where id = %s and status = 'reserved'
            returning *
            """,
            (actual_requests, actual_tokens, actual_currency_minor, reservation_id),
        ).fetchone()
        if row is None:
            raise ProblemError(
                409,
                "budget_reservation_not_reserved",
                "The budget reservation is not in a settleable state.",
            )
        return self._summary(row)

    def release(self, *, reservation_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            """
            update budget_reservations
            set status = 'released', settled_at = now()
            where id = %s and status = 'reserved'
            returning *
            """,
            (reservation_id,),
        ).fetchone()
        if row is None:
            raise ProblemError(
                409,
                "budget_reservation_not_reserved",
                "The budget reservation is not in a releasable state.",
            )
        return self._summary(row)

    def _summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "workspace_id": str(row["workspace_id"]),
            "run_id": str(row["run_id"]) if row["run_id"] else None,
            "task_id": str(row["task_id"]) if row["task_id"] else None,
            "operation": str(row["operation"]),
            "status": str(row["status"]),
            "estimated_requests": int(row["estimated_requests"]),
            "estimated_tokens": int(row["estimated_tokens"]),
            "estimated_currency_minor": int(row["estimated_currency_minor"]),
            "actual_requests": row["actual_requests"],
            "actual_tokens": row["actual_tokens"],
            "actual_currency_minor": row["actual_currency_minor"],
            "usage_date": row["usage_date"].isoformat(),
            "created_at": row["created_at"].isoformat(),
            "settled_at": row["settled_at"].isoformat() if row["settled_at"] else None,
        }
