from typing import Any

from forge_api.api.errors import ProblemError
from forge_api.application.reliability_service import RecoveryService
from forge_api.domain.identity import ActorContext, Capability
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.workflow_repositories import RunRepository
from forge_api.policy.authorization import AuthorizationService


class OperationsService:
    def __init__(self, database: Database, *, worker_id: str) -> None:
        self.database = database
        self.worker_id = worker_id

    def worker_state(self, actor: ActorContext) -> dict[str, Any]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return RunRepository(conn).worker_state_for_actor(actor_id=actor.user_id)

    def list_dead_letters(self, actor: ActorContext) -> list[dict[str, Any]]:
        if not self._can_recover(actor):
            raise ProblemError(403, "recovery_forbidden", "Recovery inspection is not allowed.")
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return RunRepository(conn).list_dead_letters_for_actor(actor_id=actor.user_id)

    def requeue_dead_letter(self, actor: ActorContext, dead_letter_id: str) -> dict[str, Any]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            dead_letters = RunRepository(conn).list_dead_letters_for_actor(actor_id=actor.user_id)
            selected = next(
                (
                    dead_letter
                    for dead_letter in dead_letters
                    if dead_letter["id"] == dead_letter_id
                ),
                None,
            )
            if selected is None:
                raise ProblemError(404, "dead_letter_not_found", "The dead letter was not found.")
            decision = AuthorizationService().decide_workspace(
                actor,
                str(selected["workspace_id"]),
                Capability.RUN_RECOVER,
            )
            if not decision.allowed:
                raise ProblemError(403, "recovery_forbidden", "Recovery inspection is not allowed.")
            tenant_id = str(selected["tenant_id"])

        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            return RunRepository(conn).requeue_dead_letter(
                actor_id=actor.user_id,
                dead_letter_id=dead_letter_id,
            )

    def recover(self, actor: ActorContext) -> dict[str, Any]:
        if not self._can_recover(actor):
            raise ProblemError(403, "recovery_forbidden", "Recovery inspection is not allowed.")
        return RecoveryService(database=self.database, worker_id=self.worker_id).scan_once()

    def _can_recover(self, actor: ActorContext) -> bool:
        return any(
            AuthorizationService()
            .decide_workspace(actor, workspace_id, Capability.RUN_RECOVER)
            .allowed
            for workspace_id in actor.workspace_roles
        )
