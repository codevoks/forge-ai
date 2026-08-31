from typing import Any

from forge_api.api.errors import ProblemError
from forge_api.domain.approvals import ApprovalDecisionValue, approval_binding_hash
from forge_api.domain.identity import ActorContext, Capability
from forge_api.infrastructure.approval_repositories import ApprovalRepository
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.repositories import IdempotencyRepository, canonical_hash
from forge_api.infrastructure.workflow_repositories import EventRepository, WorkflowRepository
from forge_api.policy.authorization import AuthorizationService


class ApprovalService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_approvals(self, actor: ActorContext) -> list[dict[str, Any]]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            return ApprovalRepository(conn).list_for_actor(actor_id=actor.user_id)

    def decide(
        self,
        actor: ActorContext,
        approval_request_id: str,
        *,
        decision: ApprovalDecisionValue,
        reason: str,
        expected_version: int,
        idempotency_key: str,
    ) -> dict[str, Any]:
        payload = {
            "approval_request_id": approval_request_id,
            "decision": decision.value,
            "reason": reason,
            "expected_version": expected_version,
        }
        request_hash = canonical_hash(payload)
        scope = f"user:{actor.user_id}:approval-decision:{approval_request_id}"

        with self.database.transaction(actor_id=actor.user_id) as conn:
            approval = ApprovalRepository(conn).get_for_actor(
                approval_request_id=approval_request_id,
            )
            decision_result = AuthorizationService().decide_workspace(
                actor,
                str(approval["workspace_id"]),
                Capability.APPROVAL_DECIDE,
            )
            if not decision_result.allowed:
                raise ProblemError(
                    403,
                    "approval_decision_forbidden",
                    "Approval decision is not allowed.",
                )
            tenant_id = str(approval["tenant_id"])

        expired_error: ProblemError | None = None
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

            repo = ApprovalRepository(conn)
            approval = repo.get_for_update(approval_request_id=approval_request_id)
            if int(approval["request_version"]) != expected_version:
                raise ProblemError(
                    409,
                    "approval_version_conflict",
                    "Approval request version changed.",
                )
            if str(approval["status"]) != "pending":
                raise ProblemError(409, "approval_not_pending", "Approval is no longer pending.")
            if actor.user_id == str(approval["requester_id"]):
                raise ProblemError(
                    403,
                    "approval_self_forbidden",
                    "The requester cannot approve their own action.",
                )

            run = WorkflowRepository(conn).workspace_scope_for_actor(
                actor_id=actor.user_id,
                workspace_id=str(approval["workspace_id"]),
            )
            if run is None:
                raise ProblemError(403, "workspace_forbidden", "The workspace is not accessible.")

            row = conn.execute(
                """
                select r.status as run_status, t.status as task_status,
                       i.action_hash, i.tool_version_id, i.input, i.status as invocation_status,
                       a.expires_at as current_expires_at
                from approval_requests a
                join runs r on r.id = a.run_id
                join tasks t on t.id = a.task_id
                join tool_invocations i on i.id = a.tool_invocation_id
                where a.id = %s
                for update of r, t, i
                """,
                (approval_request_id,),
            ).fetchone()
            if row is None:
                raise ProblemError(404, "approval_not_found", "The approval request was not found.")
            if str(row["run_status"]) != "running":
                raise ProblemError(
                    409,
                    "approval_run_not_running",
                    "The run is no longer executable.",
                )
            if str(row["task_status"]) != "waiting_approval":
                raise ProblemError(
                    409,
                    "approval_task_not_waiting",
                    "The task is not waiting for approval.",
                )
            if str(row["invocation_status"]) != "approval_required":
                raise ProblemError(
                    409,
                    "approval_invocation_not_waiting",
                    "The invocation is not waiting for approval.",
                )
            current_binding_hash = approval_binding_hash(
                tenant_id=str(approval["tenant_id"]),
                workspace_id=str(approval["workspace_id"]),
                run_id=str(approval["run_id"]),
                task_id=str(approval["task_id"]),
                tool_invocation_id=str(approval["tool_invocation_id"]),
                tool_version_id=str(row["tool_version_id"]),
                action_hash=str(row["action_hash"]),
                canonical_arguments=row["input"],
            )
            if current_binding_hash != str(approval["binding_hash"]):
                raise ProblemError(
                    409,
                    "approval_binding_mismatch",
                    "Approval no longer matches the current action.",
                )

            now_row = conn.execute("select now() as now").fetchone()
            assert now_row is not None
            expires_at = row["current_expires_at"]
            if expires_at <= now_row["now"]:
                repo.expire_pending(actor_id=actor.user_id)
                expired_error = ProblemError(409, "approval_expired", "Approval request expired.")
            else:
                decided = repo.decide(
                    approval=approval,
                    actor_id=actor.user_id,
                    decision=decision,
                    reason=reason,
                )
                EventRepository(conn).append(
                    tenant_id=str(decided["tenant_id"]),
                    workspace_id=str(decided["workspace_id"]),
                    run_id=str(decided["run_id"]),
                    task_id=str(decided["task_id"]),
                    aggregate_type="approval_request",
                    aggregate_id=str(decided["id"]),
                    event_type=f"approval.{decision.value}",
                    actor_id=actor.user_id,
                    payload={
                        "action_hash": decided["action_hash"],
                        "binding_hash": decided["binding_hash"],
                        "request_version": approval["request_version"],
                    },
                )
                if decision is ApprovalDecisionValue.APPROVED:
                    repo.resume_approved_task(approval=decided, actor_id=actor.user_id)
                    decided = repo.get_for_update(approval_request_id=approval_request_id)
                else:
                    repo.fail_rejected_task(approval=decided, actor_id=actor.user_id)

                response = {"approval_request": decided}
                idempotency.save(
                    scope=scope,
                    key=idempotency_key,
                    request_hash=request_hash,
                    response_payload=response,
                    status_code=200,
                )
                return response
        if expired_error is not None:
            raise expired_error
        raise ProblemError(500, "approval_decision_incomplete", "Approval decision did not finish.")

    def expire_pending(self, actor: ActorContext) -> dict[str, int]:
        with self.database.transaction(actor_id=actor.user_id) as conn:
            approvals = ApprovalRepository(conn).list_for_actor(actor_id=actor.user_id)
            tenant_ids = {str(approval["tenant_id"]) for approval in approvals}
        expired = 0
        for tenant_id in tenant_ids:
            with self.database.transaction(tenant_id=tenant_id, actor_id=actor.user_id) as conn:
                expired += ApprovalRepository(conn).expire_pending(actor_id=actor.user_id)
        return {"expired": expired}
