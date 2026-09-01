import time
from typing import Any

from forge_api.api.errors import ProblemError
from forge_api.application.multi_agent_router import apply_router
from forge_api.application.reliability_service import OutboxDispatcher, WorkerConsumer
from forge_api.config import Settings
from forge_api.domain.identity import ActorContext, Capability
from forge_api.domain.multi_agent import ExecutionStrategyKind, strategy_version_for
from forge_api.domain.reliability import RetryPolicy
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.multi_agent_repositories import StrategyComparisonRepository
from forge_api.infrastructure.queue import InMemoryQueue
from forge_api.infrastructure.repositories import IdempotencyRepository, canonical_hash
from forge_api.infrastructure.workflow_repositories import RunRepository, WorkflowRepository
from forge_api.policy.authorization import AuthorizationService

# A frozen, code-owned scenario (not user-supplied): the comparison must stay
# reproducible and free of cherry-picking. This objective deterministically
# routes to the deployment and customer-impact specialists on the multi-agent
# side (see domain/multi_agent.py keyword lists) and needs no approval step,
# keeping both strategies' runs directly comparable.
FROZEN_COMPARISON_OBJECTIVE = (
    "Investigate why the API deployment is slow and customers are complaining, "
    "and produce a cited conclusion."
)
MAX_DRIVE_TICKS = 80


class MultiAgentComparisonService:
    """Comparative evaluator for Phase 12: single bounded agent vs. isolated
    parallel specialists plus a deterministic synthesizer, on one frozen
    local scenario. Reuses the real durable run/task/worker/budget/policy
    architecture for both strategies; the only new persistence is the
    comparison report itself (`strategy_comparisons`), which correlates two
    already-durable run IDs rather than duplicating their state.
    """

    def __init__(self, database: Database, settings: Settings | None = None) -> None:
        self.database = database
        self.settings = settings or Settings()

    def run_comparison(
        self, actor: ActorContext, workspace_id: str, idempotency_key: str
    ) -> dict[str, Any]:
        request_hash = canonical_hash({"workspace_id": workspace_id})
        scope = f"user:{actor.user_id}:multi-agent-comparison:{workspace_id}"

        with self.database.transaction(actor_id=actor.user_id) as conn:
            workspace_scope = WorkflowRepository(conn).workspace_scope_for_actor(
                actor_id=actor.user_id, workspace_id=workspace_id
            )
            if workspace_scope is None:
                raise ProblemError(403, "workspace_forbidden", "The workspace is not accessible.")
            decision = AuthorizationService().decide_workspace(
                actor, workspace_id, Capability.RUN_CREATE
            )
            if not decision.allowed:
                raise ProblemError(
                    403,
                    "multi_agent_comparison_forbidden",
                    "Strategy comparison is not allowed.",
                )
            tenant_id = str(workspace_scope["tenant_id"])

        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            idempotency = IdempotencyRepository(conn)
            existing = idempotency.existing(scope, idempotency_key)
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise ProblemError(
                        409,
                        "idempotency_key_reused",
                        "The Idempotency-Key was already used with a different request.",
                    )
                response_payload = existing["response_payload"]
                if not isinstance(response_payload, dict):
                    raise ProblemError(
                        500, "idempotency_record_invalid", "Stored response is invalid."
                    )
                return response_payload

        single_metrics = self._run_and_measure(
            actor=actor,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            workflow_name="Bounded Agent Demo",
            strategy_kind=ExecutionStrategyKind.SINGLE_AGENTIC,
        )
        multi_metrics = self._run_and_measure(
            actor=actor,
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            workflow_name="Multi-Agent Investigation Demo",
            strategy_kind=ExecutionStrategyKind.MULTI_AGENT_PARALLEL,
        )

        caveats = (
            "Single frozen local scenario on deterministic fake models/tools; not a "
            "statistically powered study. Elapsed-second figures are measured local "
            "wall-clock overhead on this machine, not representative of live-model "
            "latency. Both strategies run the identical objective, tool grants, "
            "budgets, and security boundaries; no cherry-picking."
        )
        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            comparison = StrategyComparisonRepository(conn).create(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                single_agent_run_id=single_metrics["run_id"],
                multi_agent_run_id=multi_metrics["run_id"],
                objective=FROZEN_COMPARISON_OBJECTIVE,
                metrics={
                    "single_agentic": single_metrics,
                    "multi_agent_parallel": multi_metrics,
                },
                caveats=caveats,
                created_by=actor.user_id,
            )
            response = {"strategy_comparison": comparison}
            IdempotencyRepository(conn).save(
                scope=scope,
                key=idempotency_key,
                request_hash=request_hash,
                response_payload=response,
                status_code=201,
            )
            return response

    def get(self, actor: ActorContext, comparison_id: str) -> dict[str, Any]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return StrategyComparisonRepository(conn).get_for_actor(
                actor_id=actor.user_id, comparison_id=comparison_id
            )

    def list_comparisons(self, actor: ActorContext, workspace_id: str) -> list[dict[str, Any]]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            workspace_scope = WorkflowRepository(conn).workspace_scope_for_actor(
                actor_id=actor.user_id, workspace_id=workspace_id
            )
            if workspace_scope is None:
                raise ProblemError(403, "workspace_forbidden", "The workspace is not accessible.")
            return StrategyComparisonRepository(conn).list_for_actor(
                actor_id=actor.user_id, workspace_id=workspace_id
            )

    def _run_and_measure(
        self,
        *,
        actor: ActorContext,
        tenant_id: str,
        workspace_id: str,
        workflow_name: str,
        strategy_kind: ExecutionStrategyKind,
    ) -> dict[str, Any]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            versions = WorkflowRepository(conn).list_versions_for_actor(actor_id=actor.user_id)
        base = next(
            v
            for v in versions
            if v["name"] == workflow_name and v["workspace_id"] == workspace_id
        )
        with self.database.transaction(actor_id=actor.user_id) as conn:
            full_version = WorkflowRepository(conn).get_version_for_actor(
                actor_id=actor.user_id, version_id=base["id"]
            )

        strategy_metadata: dict[str, Any] = {}
        if strategy_kind is ExecutionStrategyKind.MULTI_AGENT_PARALLEL:
            full_version, routing_decision = apply_router(
                workflow_version=full_version, objective=FROZEN_COMPARISON_OBJECTIVE
            )
            strategy_metadata = {"routing_decision": routing_decision.model_dump(mode="json")}

        started = time.monotonic()
        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            run = RunRepository(conn).create_run(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                actor_id=actor.user_id,
                workflow_version=full_version,
                objective=FROZEN_COMPARISON_OBJECTIVE,
                constraints={},
                strategy_kind=strategy_kind.value,
                strategy_version=strategy_version_for(strategy_kind),
                strategy_metadata=strategy_metadata,
            )
        run_id = str(run["id"])
        terminal_status = self._drive_worker(actor=actor, run_id=run_id)
        elapsed_seconds = time.monotonic() - started

        with self.database.transaction(actor_id=actor.user_id) as conn:
            counters = conn.execute(
                """
                select
                  count(*) filter (
                    where decision_type = 'tool_call' and decision_status = 'validated'
                  ) as tool_calls,
                  count(*) as model_calls,
                  count(*) filter (where decision_status = 'rejected') as invalid_decisions
                from agent_iterations
                where run_id = %s
                """,
                (run_id,),
            ).fetchone()
            task_rows = conn.execute(
                "select status, count(*) as n from tasks where run_id = %s group by status",
                (run_id,),
            ).fetchall()

        return {
            "run_id": run_id,
            "terminal_status": terminal_status,
            "elapsed_seconds": round(elapsed_seconds, 4),
            "model_calls": int(counters["model_calls"]) if counters else 0,
            "tool_calls": int(counters["tool_calls"]) if counters else 0,
            "invalid_decisions": int(counters["invalid_decisions"]) if counters else 0,
            "task_status_counts": {str(row["status"]): int(row["n"]) for row in task_rows},
            "estimated_cost_usd": 0.0,
        }

    def _drive_worker(self, *, actor: ActorContext, run_id: str) -> str:
        queue = InMemoryQueue()
        dispatcher = OutboxDispatcher(
            database=self.database, queue=queue, worker_id=self.settings.worker_id
        )
        consumer = WorkerConsumer(
            database=self.database,
            queue=queue,
            worker_id=self.settings.worker_id,
            lease_seconds=self.settings.task_lease_seconds,
            retry_policy=RetryPolicy(max_attempts=self.settings.task_max_attempts),
        )
        status = "running"
        for _ in range(MAX_DRIVE_TICKS):
            dispatcher.dispatch_once()
            consumer.consume_once(block_ms=0)
            with self.database.transaction(actor_id=actor.user_id) as conn:
                run = RunRepository(conn).get_run_for_actor(actor_id=actor.user_id, run_id=run_id)
            status = str(run["status"])
            if status in {"succeeded", "failed", "cancelled"}:
                return status
        return status
