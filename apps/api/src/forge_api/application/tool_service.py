from typing import Any

from forge_api.api.errors import ProblemError
from forge_api.domain.identity import ActorContext, Capability
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.tool_repositories import (
    ToolInvocationRepository,
    ToolRegistryRepository,
)
from forge_api.infrastructure.workflow_repositories import RunRepository
from forge_api.policy.authorization import AuthorizationService


class ToolService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_tools(self, actor: ActorContext) -> list[dict[str, Any]]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return ToolRegistryRepository(conn).list_for_actor(actor_id=actor.user_id)

    def list_invocations(self, actor: ActorContext, run_id: str) -> list[dict[str, Any]]:
        tenant_id = self._authorize_run_read(actor, run_id)
        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            return ToolInvocationRepository(conn).list_invocations_for_actor(
                actor_id=actor.user_id,
                run_id=run_id,
            )

    def list_evidence(self, actor: ActorContext, run_id: str) -> list[dict[str, Any]]:
        tenant_id = self._authorize_run_read(actor, run_id)
        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            return ToolInvocationRepository(conn).list_evidence_for_actor(
                actor_id=actor.user_id,
                run_id=run_id,
            )

    def _authorize_run_read(self, actor: ActorContext, run_id: str) -> str:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            run = RunRepository(conn).get_run_for_actor(actor_id=actor.user_id, run_id=run_id)
            decision = AuthorizationService().decide_workspace(
                actor,
                str(run["workspace_id"]),
                Capability.RUN_READ,
            )
            if not decision.allowed:
                raise ProblemError(403, "run_read_forbidden", "Run reading is not allowed.")
            return str(run["tenant_id"])
