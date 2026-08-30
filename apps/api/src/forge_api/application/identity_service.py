from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.repositories import IdentityRepository, WorkspaceRepository


class IdentityService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def actor_from_claims(self, claims: dict[str, object]) -> ActorContext:
        with self.database.transaction() as conn:
            user = IdentityRepository(conn).upsert_user_from_claims(claims)
            conn.execute("select set_config('forge.actor_id', %s, true)", (str(user["id"]),))
            return IdentityRepository(conn).actor_for_user(user)

    def me(self, actor: ActorContext) -> dict[str, object]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            workspaces = WorkspaceRepository(conn).list_for_actor(actor)
        return {
            "user_id": actor.user_id,
            "external_subject": actor.external_subject,
            "email": actor.email,
            "display_name": actor.display_name,
            "workspaces": workspaces,
        }
