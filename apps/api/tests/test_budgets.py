from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from conftest import auth_headers
from fastapi.testclient import TestClient

from forge_api.api.errors import ProblemError
from forge_api.application.budget_service import BudgetService
from forge_api.application.reliability_service import OutboxDispatcher, WorkerConsumer
from forge_api.config import Settings
from forge_api.domain.budgets import BudgetEstimate
from forge_api.domain.reliability import RetryPolicy
from forge_api.infrastructure.budget_repositories import (
    BudgetPolicyRepository,
    BudgetReservationRepository,
    BudgetUsageRepository,
)
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.dev_issuer import DevIssuer
from forge_api.infrastructure.queue import InMemoryQueue
from forge_api.scripts.seed import TENANT_ID


def _headers(issuer: DevIssuer, subject: str = "alice") -> dict[str, str]:
    return auth_headers(issuer, subject)


def _workflow_by_name(client: TestClient, issuer: DevIssuer, name: str) -> Mapping[str, Any]:
    workflows = client.get("/v1/workflows", headers=_headers(issuer)).json()["workflow_versions"]
    return next(workflow for workflow in workflows if workflow["name"] == name)


def _create_run(
    client: TestClient, issuer: DevIssuer, workflow: Mapping[str, Any]
) -> Mapping[str, Any]:
    response = client.post(
        "/v1/runs",
        headers=_headers(issuer) | {"Idempotency-Key": f"phase13-budget-run-{uuid4()}"},
        json={
            "workspace_id": workflow["workspace_id"],
            "workflow_version_id": workflow["id"],
            "objective": "Exercise Phase 13 budget reservation over a real tool run.",
        },
    )
    assert response.status_code == 201
    run: Mapping[str, Any] = response.json()["run"]
    return run


def _run_worker_until_terminal(
    *,
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
    run_id: str,
) -> Mapping[str, Any]:
    queue = InMemoryQueue()
    dispatcher = OutboxDispatcher(database=database, queue=queue, worker_id=settings.worker_id)
    consumer = WorkerConsumer(
        database=database,
        queue=queue,
        worker_id=settings.worker_id,
        lease_seconds=settings.task_lease_seconds,
        retry_policy=RetryPolicy(max_attempts=settings.task_max_attempts),
    )
    run: Mapping[str, Any] = {}
    for _ in range(80):
        dispatcher.dispatch_once()
        outcome = consumer.consume_once(block_ms=0)
        if outcome == "waiting_approval":
            pending = client.get(
                "/v1/approvals", headers=_headers(issuer, "ava")
            ).json()["approval_requests"]
            for approval in pending:
                if approval["status"] != "pending":
                    continue
                client.post(
                    f"/v1/approvals/{approval['id']}:approve",
                    headers=_headers(issuer, "ava")
                    | {
                        "Idempotency-Key": f"phase13-budget-approve-{uuid4()}",
                        "If-Match": str(approval["request_version"]),
                    },
                    json={"reason": "Exercising Phase 13 budget reservations."},
                )
        run = client.get(f"/v1/runs/{run_id}", headers=_headers(issuer)).json()["run"]
        if run["status"] in {"succeeded", "failed", "cancelled"}:
            return run
    raise AssertionError("run did not become terminal")


def _alice_id(database: Database) -> str:
    with database.transaction() as conn:
        row = conn.execute(
            "select id from users where email = %s", ("alice@forge.local",)
        ).fetchone()
        assert row is not None
        return str(row["id"])


def _new_workspace(database: Database, *, created_by: str) -> str:
    workspace_id = str(uuid4())
    with database.transaction(tenant_id=TENANT_ID, actor_id=created_by) as conn:
        conn.execute(
            "insert into workspaces (id, tenant_id, name) values (%s, %s, %s)",
            (workspace_id, TENANT_ID, f"Budget test workspace {workspace_id[:8]}"),
        )
        conn.execute(
            """
            insert into memberships (tenant_id, workspace_id, user_id, role)
            values (%s, %s, %s, 'tenant_admin')
            on conflict (tenant_id, workspace_id, user_id) do update set role = excluded.role
            """,
            (TENANT_ID, workspace_id, created_by),
        )
    return workspace_id


def test_budget_estimate_rejects_negative_values() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        BudgetEstimate(requests=-1)


def test_reservation_within_ceiling_succeeds_and_updates_usage(database: Database) -> None:
    created_by = _alice_id(database)
    workspace_id = _new_workspace(database, created_by=created_by)
    with database.transaction(worker_id="test-worker") as conn:
        BudgetPolicyRepository(conn).set_workspace_policy(
            tenant_id=TENANT_ID,
            workspace_id=workspace_id,
            max_requests_per_day=3,
            max_tokens_per_day=1000,
            max_currency_minor_per_day=0,
            created_by=created_by,
        )

    service = BudgetService(database=database)
    reservation = service.reserve(
        tenant_id=TENANT_ID,
        workspace_id=workspace_id,
        run_id=None,
        task_id=None,
        worker_id="test-worker",
        operation="test:reserve",
        estimate=BudgetEstimate(requests=1, tokens=10, currency_minor=0),
        created_by=created_by,
    )
    assert reservation["status"] == "reserved"

    with database.transaction(worker_id="test-worker") as conn:
        usage = BudgetUsageRepository(conn).get_for_actor(
            tenant_id=TENANT_ID, workspace_id=workspace_id, usage_date=datetime.now(UTC).date()
        )
    assert usage["requests_used"] == 1
    assert usage["tokens_used"] == 10


def test_reservation_exceeding_ceiling_is_rejected_with_problem_error(database: Database) -> None:
    created_by = _alice_id(database)
    workspace_id = _new_workspace(database, created_by=created_by)
    with database.transaction(worker_id="test-worker") as conn:
        BudgetPolicyRepository(conn).set_workspace_policy(
            tenant_id=TENANT_ID,
            workspace_id=workspace_id,
            max_requests_per_day=1,
            max_tokens_per_day=1000,
            max_currency_minor_per_day=0,
            created_by=created_by,
        )

    service = BudgetService(database=database)
    service.reserve(
        tenant_id=TENANT_ID,
        workspace_id=workspace_id,
        run_id=None,
        task_id=None,
        worker_id="test-worker",
        operation="test:first",
        estimate=BudgetEstimate(requests=1),
        created_by=created_by,
    )

    with pytest.raises(ProblemError) as exc_info:
        service.reserve(
            tenant_id=TENANT_ID,
            workspace_id=workspace_id,
            run_id=None,
            task_id=None,
            worker_id="test-worker",
            operation="test:second",
            estimate=BudgetEstimate(requests=1),
            created_by=created_by,
        )
    assert exc_info.value.status_code == 429
    assert exc_info.value.code == "budget_exceeded"


def test_release_returns_reserved_amount_to_the_ceiling(database: Database) -> None:
    created_by = _alice_id(database)
    workspace_id = _new_workspace(database, created_by=created_by)
    with database.transaction(worker_id="test-worker") as conn:
        BudgetPolicyRepository(conn).set_workspace_policy(
            tenant_id=TENANT_ID,
            workspace_id=workspace_id,
            max_requests_per_day=1,
            max_tokens_per_day=1000,
            max_currency_minor_per_day=0,
            created_by=created_by,
        )

    service = BudgetService(database=database)
    reservation = service.reserve(
        tenant_id=TENANT_ID,
        workspace_id=workspace_id,
        run_id=None,
        task_id=None,
        worker_id="test-worker",
        operation="test:release-me",
        estimate=BudgetEstimate(requests=1),
        created_by=created_by,
    )
    service.release(
        reservation_id=str(reservation["id"]),
        tenant_id=TENANT_ID,
        workspace_id=workspace_id,
        worker_id="test-worker",
    )

    second = service.reserve(
        tenant_id=TENANT_ID,
        workspace_id=workspace_id,
        run_id=None,
        task_id=None,
        worker_id="test-worker",
        operation="test:after-release",
        estimate=BudgetEstimate(requests=1),
        created_by=created_by,
    )
    assert second["status"] == "reserved"


def test_settle_adjusts_usage_by_the_delta_between_estimate_and_actual(database: Database) -> None:
    created_by = _alice_id(database)
    workspace_id = _new_workspace(database, created_by=created_by)
    with database.transaction(worker_id="test-worker") as conn:
        BudgetPolicyRepository(conn).set_workspace_policy(
            tenant_id=TENANT_ID,
            workspace_id=workspace_id,
            max_requests_per_day=10,
            max_tokens_per_day=1000,
            max_currency_minor_per_day=0,
            created_by=created_by,
        )

    service = BudgetService(database=database)
    reservation = service.reserve(
        tenant_id=TENANT_ID,
        workspace_id=workspace_id,
        run_id=None,
        task_id=None,
        worker_id="test-worker",
        operation="test:settle",
        estimate=BudgetEstimate(requests=1, tokens=100),
        created_by=created_by,
    )
    service.settle(
        reservation_id=str(reservation["id"]),
        tenant_id=TENANT_ID,
        workspace_id=workspace_id,
        worker_id="test-worker",
        actual=BudgetEstimate(requests=1, tokens=40),
    )

    with database.transaction(worker_id="test-worker") as conn:
        usage = BudgetUsageRepository(conn).get_for_actor(
            tenant_id=TENANT_ID,
            workspace_id=workspace_id,
            usage_date=datetime.now(UTC).date(),
        )
    assert usage["tokens_used"] == 40


def test_concurrent_reservations_never_exceed_the_daily_ceiling(database: Database) -> None:
    created_by = _alice_id(database)
    workspace_id = _new_workspace(database, created_by=created_by)
    max_requests = 5
    with database.transaction(worker_id="test-worker") as conn:
        BudgetPolicyRepository(conn).set_workspace_policy(
            tenant_id=TENANT_ID,
            workspace_id=workspace_id,
            max_requests_per_day=max_requests,
            max_tokens_per_day=100_000,
            max_currency_minor_per_day=0,
            created_by=created_by,
        )

    service = BudgetService(database=database)

    def attempt(index: int) -> bool:
        try:
            service.reserve(
                tenant_id=TENANT_ID,
                workspace_id=workspace_id,
                run_id=None,
                task_id=None,
                worker_id="test-worker",
                operation=f"test:race-{index}",
                estimate=BudgetEstimate(requests=1),
                created_by=created_by,
            )
            return True
        except ProblemError as exc:
            assert exc.code == "budget_exceeded"
            return False

    with ThreadPoolExecutor(max_workers=20) as executor:
        results = list(executor.map(attempt, range(20)))

    assert sum(results) == max_requests
    with database.transaction(worker_id="test-worker") as conn:
        usage = BudgetUsageRepository(conn).get_for_actor(
            tenant_id=TENANT_ID,
            workspace_id=workspace_id,
            usage_date=datetime.now(UTC).date(),
        )
    assert usage["requests_used"] == max_requests


def test_real_tool_run_reserves_and_settles_budget_for_every_tool_call(
    database: Database,
    settings: Settings,
    client: TestClient,
    issuer: DevIssuer,
) -> None:
    workflow = _workflow_by_name(client, issuer, "Typed Tool Demo")
    run = _create_run(client, issuer, workflow)

    completed = _run_worker_until_terminal(
        database=database, settings=settings, client=client, issuer=issuer, run_id=str(run["id"])
    )
    assert completed["status"] == "succeeded"

    with database.transaction(worker_id="test-worker") as conn:
        reservations = conn.execute(
            "select status, operation from budget_reservations where run_id = %s", (run["id"],)
        ).fetchall()
    assert len(reservations) == 3
    assert {row["status"] for row in reservations} == {"settled"}
    assert {row["operation"] for row in reservations} == {
        "tool:deployment_history.lookup",
        "tool:customer_reports.search",
        "tool:ticket.create_simulated",
    }

    usage_response = client.get(
        "/v1/budgets/usage",
        params={"workspace_id": workflow["workspace_id"]},
        headers=_headers(issuer),
    )
    assert usage_response.status_code == 200
    body = usage_response.json()
    assert body["policy"]["max_currency_minor_per_day"] == 0
    assert body["usage"]["requests_used"] >= 3


@pytest.mark.security
def test_budget_usage_endpoint_rejects_a_non_member_workspace(
    client: TestClient, issuer: DevIssuer
) -> None:
    response = client.get(
        "/v1/budgets/usage",
        params={"workspace_id": str(uuid4())},
        headers=_headers(issuer, "mallory"),
    )
    assert response.status_code == 403


@pytest.mark.security
def test_budget_tables_are_hidden_without_transaction_scope(database: Database) -> None:
    created_by = _alice_id(database)
    workspace_id = _new_workspace(database, created_by=created_by)
    with database.transaction(worker_id="test-worker") as conn:
        BudgetPolicyRepository(conn).set_workspace_policy(
            tenant_id=TENANT_ID,
            workspace_id=workspace_id,
            max_requests_per_day=5,
            max_tokens_per_day=1000,
            max_currency_minor_per_day=0,
            created_by=created_by,
        )
    with database.transaction() as conn:
        rows = conn.execute(
            "select * from budget_policies where workspace_id = %s", (workspace_id,)
        ).fetchall()
    assert rows == []


@pytest.mark.security
def test_budget_reservations_are_hidden_across_tenants(database: Database) -> None:
    created_by = _alice_id(database)
    workspace_id = _new_workspace(database, created_by=created_by)
    with database.transaction(worker_id="test-worker") as conn:
        BudgetPolicyRepository(conn).set_workspace_policy(
            tenant_id=TENANT_ID,
            workspace_id=workspace_id,
            max_requests_per_day=5,
            max_tokens_per_day=1000,
            max_currency_minor_per_day=0,
            created_by=created_by,
        )
        reservation = BudgetReservationRepository(conn).create(
            tenant_id=TENANT_ID,
            workspace_id=workspace_id,
            run_id=None,
            task_id=None,
            operation="test:cross-tenant",
            estimated_requests=1,
            estimated_tokens=0,
            estimated_currency_minor=0,
            usage_date=datetime.now(UTC).date(),
        )

    other_tenant_id = str(uuid4())
    with database.transaction(tenant_id=other_tenant_id) as conn:
        conn.execute(
            "insert into tenants (id, name) values (%s, %s)", (other_tenant_id, "Other Tenant")
        )
        rows = conn.execute(
            "select * from budget_reservations where id = %s", (reservation["id"],)
        ).fetchall()
    assert rows == []


@pytest.mark.security
def test_budget_reservation_write_requires_tenant_or_worker_context(
    database: Database,
) -> None:
    created_by = _alice_id(database)
    workspace_id = _new_workspace(database, created_by=created_by)
    with database.transaction() as conn:
        with pytest.raises(Exception, match="row-level security"):
            BudgetReservationRepository(conn).create(
                tenant_id=TENANT_ID,
                workspace_id=workspace_id,
                run_id=None,
                task_id=None,
                operation="test:no-scope-context",
                estimated_requests=1,
                estimated_tokens=0,
                estimated_currency_minor=0,
                usage_date=datetime.now(UTC).date(),
            )
