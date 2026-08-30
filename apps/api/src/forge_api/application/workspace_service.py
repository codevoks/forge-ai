from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.repositories import WorkspaceRepository


class WorkspaceService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_for_actor(self, actor: ActorContext) -> list[dict[str, object]]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return WorkspaceRepository(conn).list_for_actor(actor)

    def get_for_actor(self, actor: ActorContext, workspace_id: str) -> dict[str, object]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return WorkspaceRepository(conn).get_for_actor(actor, workspace_id)
