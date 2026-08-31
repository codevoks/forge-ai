from forge_api.api.errors import ProblemError
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.agent_repositories import AgentRepository
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.workflow_repositories import RunRepository


class AgentService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_iterations(self, actor: ActorContext, run_id: str) -> list[dict[str, object]]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            run = RunRepository(conn).get_run_for_actor(actor_id=actor.user_id, run_id=run_id)
            tenant_id = str(run["tenant_id"])
        with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
            RunRepository(conn).get_run_for_actor(actor_id=actor.user_id, run_id=run_id)
            return AgentRepository(conn).list_iterations_for_actor(
                actor_id=actor.user_id,
                run_id=run_id,
            )

    def get_iteration_count(self, actor: ActorContext, run_id: str) -> int:
        iterations = self.list_iterations(actor, run_id)
        if not isinstance(iterations, list):
            raise ProblemError(500, "agent_iterations_invalid", "Agent iterations are invalid.")
        return len(iterations)
