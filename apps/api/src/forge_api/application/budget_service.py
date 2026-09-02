"""Reserve-before-work, settle/release-after budget enforcement.

Every model/tool call estimates its own upper-bound cost, reserves it
atomically against the workspace's daily ceiling (see
`infrastructure/budget_repositories.py::BudgetUsageRepository.try_reserve`
for the race-safe conditional `UPDATE`), then settles the reservation to
actual usage once the call completes, or releases it if the call never
executes. A rejected reservation raises `ProblemError(429, "budget_exceeded",
...)` before any adapter is invoked — the budget boundary is enforced by
Forge application code, never by a model's own self-reported estimate.
"""

from datetime import UTC, date, datetime
from typing import Any

from forge_api.api.errors import ProblemError
from forge_api.domain.budgets import BudgetEstimate
from forge_api.infrastructure.budget_repositories import (
    BudgetPolicyRepository,
    BudgetReservationRepository,
    BudgetUsageRepository,
)
from forge_api.infrastructure.database import Database


def _today() -> date:
    return datetime.now(UTC).date()


class BudgetService:
    def __init__(self, *, database: Database) -> None:
        self.database = database

    def reserve(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        run_id: str | None,
        task_id: str | None,
        worker_id: str,
        operation: str,
        estimate: BudgetEstimate,
        created_by: str,
    ) -> dict[str, Any]:
        usage_date = _today()
        with self.database.transaction(worker_id=worker_id) as conn:
            policy = BudgetPolicyRepository(conn).get_or_create_workspace_policy(
                tenant_id=tenant_id, workspace_id=workspace_id, created_by=created_by
            )
            granted = BudgetUsageRepository(conn).try_reserve(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                usage_date=usage_date,
                requests=estimate.requests,
                tokens=estimate.tokens,
                currency_minor=estimate.currency_minor,
                max_requests=policy["max_requests_per_day"],
                max_tokens=policy["max_tokens_per_day"],
                max_currency_minor=policy["max_currency_minor_per_day"],
            )
            if not granted:
                raise ProblemError(
                    429,
                    "budget_exceeded",
                    "The workspace daily budget would be exceeded by this operation.",
                    retryable=False,
                )
            reservation = BudgetReservationRepository(conn).create(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                run_id=run_id,
                task_id=task_id,
                operation=operation,
                estimated_requests=estimate.requests,
                estimated_tokens=estimate.tokens,
                estimated_currency_minor=estimate.currency_minor,
                usage_date=usage_date,
            )
            return reservation

    def settle(
        self,
        *,
        reservation_id: str,
        tenant_id: str,
        workspace_id: str,
        worker_id: str,
        actual: BudgetEstimate,
    ) -> dict[str, Any]:
        with self.database.transaction(worker_id=worker_id) as conn:
            reservation_repo = BudgetReservationRepository(conn)
            reservation = reservation_repo.get_for_update(reservation_id=reservation_id)
            settled = reservation_repo.settle(
                reservation_id=reservation_id,
                actual_requests=actual.requests,
                actual_tokens=actual.tokens,
                actual_currency_minor=actual.currency_minor,
            )
            delta_requests = actual.requests - reservation["estimated_requests"]
            delta_tokens = actual.tokens - reservation["estimated_tokens"]
            delta_currency_minor = actual.currency_minor - reservation["estimated_currency_minor"]
            if delta_requests or delta_tokens or delta_currency_minor:
                BudgetUsageRepository(conn).adjust(
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    usage_date=date.fromisoformat(str(reservation["usage_date"])),
                    delta_requests=delta_requests,
                    delta_tokens=delta_tokens,
                    delta_currency_minor=delta_currency_minor,
                )
            return settled

    def release(
        self,
        *,
        reservation_id: str,
        tenant_id: str,
        workspace_id: str,
        worker_id: str,
    ) -> dict[str, Any]:
        with self.database.transaction(worker_id=worker_id) as conn:
            reservation_repo = BudgetReservationRepository(conn)
            reservation = reservation_repo.get_for_update(reservation_id=reservation_id)
            released = reservation_repo.release(reservation_id=reservation_id)
            BudgetUsageRepository(conn).adjust(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                usage_date=date.fromisoformat(str(reservation["usage_date"])),
                delta_requests=-reservation["estimated_requests"],
                delta_tokens=-reservation["estimated_tokens"],
                delta_currency_minor=-reservation["estimated_currency_minor"],
            )
            return released
