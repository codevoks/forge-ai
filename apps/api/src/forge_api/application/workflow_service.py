from typing import Any

from forge_api.api.errors import ProblemError
from forge_api.domain.identity import ActorContext, Capability
from forge_api.domain.workflow import (
    DAGValidator,
    WorkflowEdgeDefinition,
    WorkflowStepDefinition,
)
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.repositories import IdempotencyRepository, canonical_hash
from forge_api.infrastructure.workflow_repositories import EventRepository, WorkflowRepository
from forge_api.policy.authorization import AuthorizationService


class WorkflowService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create_published_version(
        self,
        actor: ActorContext,
        idempotency_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        steps = [
            WorkflowStepDefinition(
                key=str(step["key"]),
                name=str(step["name"]),
                kind=str(step["kind"]),
                input=dict(step.get("input", {})),
            )
            for step in payload["steps"]
        ]
        edges = [
            WorkflowEdgeDefinition(from_key=str(edge["from"]), to_key=str(edge["to"]))
            for edge in payload.get("edges", [])
        ]
        DAGValidator().validate(steps=steps, edges=edges)
        request_hash = canonical_hash(payload)
        workspace_id = str(payload["workspace_id"])
        scope = f"user:{actor.user_id}:workflow-create:{workspace_id}"

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
                Capability.WORKFLOW_PUBLISH,
            )
            if not decision.allowed:
                raise ProblemError(
                    403, "workflow_publish_forbidden", "Workflow publication is not allowed."
                )

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

            workflows = WorkflowRepository(conn)
            version = workflows.create_published_version(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                actor_id=actor.user_id,
                name=str(payload["name"]),
                steps=[step.__dict__ | {"input": step.input} for step in steps],
                edges=[{"from": edge.from_key, "to": edge.to_key} for edge in edges],
            )
            EventRepository(conn).append(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                run_id=None,
                task_id=None,
                aggregate_type="workflow_version",
                aggregate_id=str(version["id"]),
                event_type="workflow_version.published",
                actor_id=actor.user_id,
                payload={
                    "template_id": version["template_id"],
                    "version_number": version["version_number"],
                },
            )
            response = {"workflow_version": version}
            idempotency.save(
                scope=scope,
                key=idempotency_key,
                request_hash=request_hash,
                response_payload=response,
                status_code=201,
            )
            return response

    def list_versions(self, actor: ActorContext) -> list[dict[str, Any]]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return WorkflowRepository(conn).list_versions_for_actor(actor_id=actor.user_id)

    def get_version(self, actor: ActorContext, version_id: str) -> dict[str, Any]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return WorkflowRepository(conn).get_version_for_actor(
                actor_id=actor.user_id,
                version_id=version_id,
            )
