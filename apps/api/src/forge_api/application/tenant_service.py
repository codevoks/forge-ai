from forge_api.api.errors import ProblemError
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.ids import uuid7
from forge_api.infrastructure.repositories import (
    IdempotencyRepository,
    TenantRepository,
    canonical_hash,
)


class TenantService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        actor: ActorContext,
        idempotency_key: str,
        payload: dict[str, str],
    ) -> dict[str, object]:
        request_hash = canonical_hash(payload)
        scope = f"user:{actor.user_id}:tenant-create"
        tenant_id = str(uuid7())
        workspace_id = str(uuid7())
        tenant_name = payload["name"]
        workspace_name = payload.get("workspace_name") or f"{tenant_name} Workspace"

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
                        500,
                        "idempotency_record_invalid",
                        "Stored response is invalid.",
                    )
                return response_payload

            result = TenantRepository(conn).create_tenant_with_workspace(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                user_id=actor.user_id,
                tenant_name=tenant_name,
                workspace_name=workspace_name,
            )
            response: dict[str, object] = {
                "tenant": {
                    "id": str(result["tenant"]["id"]),
                    "name": result["tenant"]["name"],
                    "version": result["tenant"]["version"],
                },
                "workspace": {
                    "id": str(result["workspace"]["id"]),
                    "tenant_id": str(result["workspace"]["tenant_id"]),
                    "name": result["workspace"]["name"],
                    "version": result["workspace"]["version"],
                },
            }
            idempotency.save(
                scope=scope,
                key=idempotency_key,
                request_hash=request_hash,
                response_payload=response,
                status_code=201,
            )
            return response
