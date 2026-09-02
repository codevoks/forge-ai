from typing import Any, Literal

from forge_api.api.errors import ProblemError
from forge_api.config import Settings
from forge_api.domain.debugging import ReplayMode
from forge_api.domain.identity import ActorContext, Capability
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.debugging_repositories import (
    DebuggerRepository,
    decode_event_cursor,
)
from forge_api.infrastructure.repositories import IdempotencyRepository, canonical_hash
from forge_api.policy.authorization import AuthorizationService


class DebuggingService:
    def __init__(self, database: Database, settings: Settings | None = None) -> None:
        self.database = database
        self.settings = settings or Settings()

    def get_debugger(self, actor: ActorContext, run_id: str) -> dict[str, Any]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            run = DebuggerRepository(conn).get_run_for_actor(
                actor_id=actor.user_id,
                run_id=run_id,
            )
            decision = AuthorizationService().decide_workspace(
                actor,
                str(run["workspace_id"]),
                Capability.RUN_READ,
            )
            if not decision.allowed:
                raise ProblemError(403, "debugger_forbidden", "Run debugging is not allowed.")
            return DebuggerRepository(conn).debugger_snapshot(
                actor_id=actor.user_id,
                run_id=run_id,
            )

    def event_feed(
        self,
        actor: ActorContext,
        run_id: str,
        *,
        cursor: str | None,
        limit: int,
    ) -> dict[str, Any]:
        after_sequence = 0
        if cursor:
            after_sequence = decode_event_cursor(cursor, expected_run_id=run_id)
        with self.database.transaction(actor_id=actor.user_id) as conn:
            run = DebuggerRepository(conn).get_run_for_actor(
                actor_id=actor.user_id,
                run_id=run_id,
            )
            decision = AuthorizationService().decide_workspace(
                actor,
                str(run["workspace_id"]),
                Capability.RUN_READ,
            )
            if not decision.allowed:
                raise ProblemError(403, "debugger_forbidden", "Run debugging is not allowed.")
            return DebuggerRepository(conn).event_feed(
                actor_id=actor.user_id,
                run_id=run_id,
                after_sequence=after_sequence,
                limit=limit,
            )

    def verify_projection(
        self,
        actor: ActorContext,
        run_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {"run_id": run_id, "operation": "projection_verify"}
        request_hash = canonical_hash(payload)
        scope = f"user:{actor.user_id}:debug-projection:{run_id}"
        with self.database.transaction(actor_id=actor.user_id) as conn:
            run = DebuggerRepository(conn).get_run_for_actor(
                actor_id=actor.user_id,
                run_id=run_id,
            )
            decision = AuthorizationService().decide_workspace(
                actor,
                str(run["workspace_id"]),
                Capability.RUN_RECOVER,
            )
            if not decision.allowed:
                raise ProblemError(
                    403,
                    "projection_verify_forbidden",
                    "Projection verification is not allowed.",
                )
            tenant_id = str(run["tenant_id"])
            workspace_id = str(run["workspace_id"])

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
            verification = DebuggerRepository(conn).verify_projection(
                actor_id=actor.user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                run_id=run_id,
            )
            response = {"projection_verification": verification}
            idempotency.save(
                scope=scope,
                key=idempotency_key,
                request_hash=request_hash,
                response_payload=response,
                status_code=201,
            )
            return response

    def create_replay(
        self,
        actor: ActorContext,
        run_id: str,
        *,
        mode: Literal["simulation", "effect_replay"],
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {"run_id": run_id, "mode": mode}
        request_hash = canonical_hash(payload)
        scope = f"user:{actor.user_id}:debug-replay:{run_id}"
        with self.database.transaction(actor_id=actor.user_id) as conn:
            run = DebuggerRepository(conn).get_run_for_actor(
                actor_id=actor.user_id,
                run_id=run_id,
            )
            decision = AuthorizationService().decide_workspace(
                actor,
                str(run["workspace_id"]),
                Capability.RUN_RECOVER,
            )
            if not decision.allowed:
                raise ProblemError(403, "replay_forbidden", "Replay is not allowed.")
            tenant_id = str(run["tenant_id"])
            workspace_id = str(run["workspace_id"])

        replay_mode = ReplayMode(mode)
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
            replay = DebuggerRepository(conn).create_replay_session(
                actor_id=actor.user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                run_id=run_id,
                mode=replay_mode,
            )
            response = {"replay_session": replay}
            idempotency.save(
                scope=scope,
                key=idempotency_key,
                request_hash=request_hash,
                response_payload=response,
                status_code=201,
            )
            return response

    def create_trace_export(
        self,
        actor: ActorContext,
        run_id: str,
        *,
        exporter: Literal["local", "langsmith", "langfuse"],
        mode: Literal["local", "disabled", "enabled"],
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {"run_id": run_id, "exporter": exporter, "mode": mode}
        request_hash = canonical_hash(payload)
        scope = f"user:{actor.user_id}:debug-trace-export:{run_id}"
        with self.database.transaction(actor_id=actor.user_id) as conn:
            run = DebuggerRepository(conn).get_run_for_actor(
                actor_id=actor.user_id,
                run_id=run_id,
            )
            decision = AuthorizationService().decide_workspace(
                actor,
                str(run["workspace_id"]),
                Capability.RUN_RECOVER,
            )
            if not decision.allowed:
                raise ProblemError(403, "trace_export_forbidden", "Trace export is not allowed.")
            tenant_id = str(run["tenant_id"])
            workspace_id = str(run["workspace_id"])

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
            trace_export = DebuggerRepository(conn).create_trace_export(
                actor_id=actor.user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                run_id=run_id,
                exporter=exporter,
                mode=mode,
                external_integrations=self.settings.external_integrations,
            )
            response = {"trace_export": trace_export}
            idempotency.save(
                scope=scope,
                key=idempotency_key,
                request_hash=request_hash,
                response_payload=response,
                status_code=201,
            )
            return response
