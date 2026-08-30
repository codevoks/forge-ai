from typing import Any

from forge_api.api.errors import ProblemError
from forge_api.domain.identity import ActorContext, Capability
from forge_api.domain.workflow import validate_payload_size
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.repositories import IdempotencyRepository, canonical_hash
from forge_api.infrastructure.workflow_repositories import RunRepository, WorkflowRepository
from forge_api.policy.authorization import AuthorizationService


class RunService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        actor: ActorContext,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        validate_payload_size(str(payload["objective"]), field="objective")
        request_hash = canonical_hash(payload)
        workspace_id = str(payload["workspace_id"])
        workflow_version_id = str(payload["workflow_version_id"])
        scope = f"user:{actor.user_id}:run-create:{workspace_id}"

        with self.database.transaction(actor_id=actor.user_id) as conn:
            workflows = WorkflowRepository(conn)
            workspace_scope = workflows.workspace_scope_for_actor(
                actor_id=actor.user_id,
                workspace_id=workspace_id,
            )
            if workspace_scope is None:
                raise ProblemError(403, "workspace_forbidden", "The workspace is not accessible.")
            tenant_id = str(workspace_scope["tenant_id"])
            decision = AuthorizationService().decide_workspace(
                actor,
                workspace_id,
                Capability.RUN_CREATE,
            )
            if not decision.allowed:
                raise ProblemError(403, "run_create_forbidden", "Run creation is not allowed.")

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

            workflow_version = WorkflowRepository(conn).get_version_for_actor(
                actor_id=actor.user_id,
                version_id=workflow_version_id,
            )
            if workflow_version["workspace_id"] != workspace_id:
                raise ProblemError(
                    422, "workflow_workspace_mismatch", "Workflow version is not in the workspace."
                )
            run = RunRepository(conn).create_run(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                actor_id=actor.user_id,
                workflow_version=workflow_version,
                objective=str(payload["objective"]),
                constraints=dict(payload.get("constraints", {})),
            )
            response = {"run": run}
            idempotency.save(
                scope=scope,
                key=idempotency_key,
                request_hash=request_hash,
                response_payload=response,
                status_code=201,
            )
            return response

    def list_runs(self, actor: ActorContext) -> list[dict[str, Any]]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return RunRepository(conn).list_runs_for_actor(actor_id=actor.user_id)

    def get(self, actor: ActorContext, run_id: str) -> dict[str, Any]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return RunRepository(conn).get_run_for_actor(actor_id=actor.user_id, run_id=run_id)

    def list_tasks(self, actor: ActorContext, run_id: str) -> list[dict[str, Any]]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return RunRepository(conn).list_tasks_for_actor(actor_id=actor.user_id, run_id=run_id)

    def list_events(self, actor: ActorContext, run_id: str) -> list[dict[str, Any]]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return RunRepository(conn).list_events_for_actor(actor_id=actor.user_id, run_id=run_id)

    def advance_one_ready_task(self, actor: ActorContext, run_id: str) -> dict[str, Any]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            run = RunRepository(conn).get_run_for_actor(actor_id=actor.user_id, run_id=run_id)
            decision = AuthorizationService().decide_workspace(
                actor,
                str(run["workspace_id"]),
                Capability.RUN_CREATE,
            )
            if not decision.allowed:
                raise ProblemError(403, "run_advance_forbidden", "Run advancement is not allowed.")
            tenant_id = str(run["tenant_id"])

        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            return RunRepository(conn).advance_one_ready_task(actor_id=actor.user_id, run_id=run_id)

    def cancel(self, actor: ActorContext, run_id: str, reason: str) -> dict[str, Any]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            run = RunRepository(conn).get_run_for_actor(actor_id=actor.user_id, run_id=run_id)
            decision = AuthorizationService().decide_workspace(
                actor,
                str(run["workspace_id"]),
                Capability.RUN_CREATE,
            )
            if not decision.allowed:
                raise ProblemError(403, "run_cancel_forbidden", "Run cancellation is not allowed.")
            tenant_id = str(run["tenant_id"])

        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            return RunRepository(conn).cancel_run(
                actor_id=actor.user_id,
                run_id=run_id,
                reason=reason,
            )

    def worker_state(self, actor: ActorContext) -> dict[str, Any]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return RunRepository(conn).worker_state_for_actor(actor_id=actor.user_id)
