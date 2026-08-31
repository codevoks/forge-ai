import json
from typing import Any

from psycopg import Connection

from forge_api.api.errors import ProblemError
from forge_api.domain.approvals import (
    APPROVAL_TTL_MINUTES,
    MAX_PENDING_APPROVALS_PER_RUN,
    ApprovalDecisionValue,
    approval_binding_hash,
)
from forge_api.infrastructure.ids import uuid7
from forge_api.infrastructure.workflow_repositories import EventRepository, OutboxRepository


class ApprovalRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn
        self.events = EventRepository(conn)
        self.outbox = OutboxRepository(conn)

    def require_for_invocation(
        self,
        *,
        claim: dict[str, Any],
        invocation: dict[str, Any],
        canonical_arguments: dict[str, object],
        reason: str,
    ) -> dict[str, Any]:
        pending_count = self.conn.execute(
            """
            select count(*) as count
            from approval_requests
            where run_id = %s and status = 'pending'
            """,
            (claim["run_id"],),
        ).fetchone()
        if (
            pending_count is not None
            and int(pending_count["count"]) >= MAX_PENDING_APPROVALS_PER_RUN
        ):
            raise ProblemError(
                429,
                "approval_budget_exhausted",
                "The run has too many pending approval requests.",
            )

        binding_hash = approval_binding_hash(
            tenant_id=str(claim["tenant_id"]),
            workspace_id=str(claim["workspace_id"]),
            run_id=str(claim["run_id"]),
            task_id=str(claim["task_id"]),
            tool_invocation_id=str(invocation["id"]),
            tool_version_id=str(invocation["tool_version_id"]),
            action_hash=str(invocation["action_hash"]),
            canonical_arguments=canonical_arguments,
        )
        action_summary = {
            "tool_name": invocation["tool_name"],
            "tool_version": invocation["tool_version"],
            "risk": invocation["risk"],
            "action_hash": invocation["action_hash"],
            "arguments": canonical_arguments,
            "effect": "local simulated effect; no external provider call",
        }
        row = self.conn.execute(
            """
            insert into approval_requests
              (id, tenant_id, workspace_id, run_id, task_id, tool_invocation_id,
               tool_version_id, requester_id, action_hash, binding_hash, risk,
               reason, action_summary, status, expires_at)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'pending', now() + (%s || ' minutes')::interval)
            on conflict (tool_invocation_id, action_hash) do update
              set updated_at = approval_requests.updated_at
            returning *
            """,
            (
                str(uuid7()),
                claim["tenant_id"],
                claim["workspace_id"],
                claim["run_id"],
                claim["task_id"],
                invocation["id"],
                invocation["tool_version_id"],
                claim["actor_id"],
                invocation["action_hash"],
                binding_hash,
                invocation["risk"],
                reason,
                json.dumps(action_summary),
                APPROVAL_TTL_MINUTES,
            ),
        ).fetchone()
        assert row is not None
        self.conn.execute(
            """
            update tool_invocations
            set status = 'approval_required', updated_at = now()
            where id = %s and status in ('intent_recorded', 'approval_required')
            """,
            (invocation["id"],),
        )
        self.conn.execute(
            """
            update task_attempts
            set status = 'waiting_approval', completed_at = now()
            where id = %s and status = 'running'
            """,
            (claim["attempt_id"],),
        )
        self.conn.execute(
            """
            update tasks
            set status = 'waiting_approval', version = version + 1, updated_at = now()
            where id = %s and status = 'running'
            """,
            (claim["task_id"],),
        )
        self.events.append(
            tenant_id=str(claim["tenant_id"]),
            workspace_id=str(claim["workspace_id"]),
            run_id=str(claim["run_id"]),
            task_id=str(claim["task_id"]),
            aggregate_type="approval_request",
            aggregate_id=str(row["id"]),
            event_type="approval.requested",
            actor_id=str(claim["actor_id"]),
            payload={
                "tool_name": invocation["tool_name"],
                "tool_version": invocation["tool_version"],
                "risk": invocation["risk"],
                "action_hash": invocation["action_hash"],
                "binding_hash": binding_hash,
            },
        )
        return self._summary(row)

    def approved_request_for_invocation(
        self,
        *,
        invocation: dict[str, Any],
        canonical_arguments: dict[str, object],
    ) -> dict[str, Any] | None:
        binding_hash = approval_binding_hash(
            tenant_id=str(invocation["tenant_id"]),
            workspace_id=str(invocation["workspace_id"]),
            run_id=str(invocation["run_id"]),
            task_id=str(invocation["task_id"]),
            tool_invocation_id=str(invocation["id"]),
            tool_version_id=str(invocation["tool_version_id"]),
            action_hash=str(invocation["action_hash"]),
            canonical_arguments=canonical_arguments,
        )
        row = self.conn.execute(
            """
            select *
            from approval_requests
            where tool_invocation_id = %s
              and action_hash = %s
              and binding_hash = %s
              and status = 'approved'
              and expires_at > now()
            for update
            """,
            (invocation["id"], invocation["action_hash"], binding_hash),
        ).fetchone()
        return self._summary(row) if row is not None else None

    def consume_approved_request(self, *, approval_request_id: str) -> None:
        row = self.conn.execute(
            """
            update approval_requests
            set status = 'consumed',
                consumed_at = now(),
                updated_at = now(),
                request_version = request_version + 1
            where id = %s and status = 'approved'
            returning *
            """,
            (approval_request_id,),
        ).fetchone()
        if row is None:
            raise ProblemError(409, "approval_not_consumable", "Approval cannot be consumed.")

    def list_for_actor(self, *, actor_id: str) -> list[dict[str, Any]]:
        _ = actor_id
        rows = self.conn.execute(
            """
            select *
            from approval_requests
            order by created_at desc
            limit 100
            """
        ).fetchall()
        return [self._summary(row) for row in rows]

    def get_for_update(self, *, approval_request_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "select * from approval_requests where id = %s for update",
            (approval_request_id,),
        ).fetchone()
        if row is None:
            raise ProblemError(404, "approval_not_found", "The approval request was not found.")
        return self._summary(row)

    def get_for_actor(self, *, approval_request_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            "select * from approval_requests where id = %s",
            (approval_request_id,),
        ).fetchone()
        if row is None:
            raise ProblemError(404, "approval_not_found", "The approval request was not found.")
        return self._summary(row)

    def decide(
        self,
        *,
        approval: dict[str, Any],
        actor_id: str,
        decision: ApprovalDecisionValue,
        reason: str,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            insert into approval_decisions
              (id, tenant_id, workspace_id, approval_request_id, decision,
               decided_by, reason, request_version, binding_hash)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning *
            """,
            (
                str(uuid7()),
                approval["tenant_id"],
                approval["workspace_id"],
                approval["id"],
                decision.value,
                actor_id,
                reason,
                approval["request_version"],
                approval["binding_hash"],
            ),
        ).fetchone()
        assert row is not None
        updated = self.conn.execute(
            """
            update approval_requests
            set status = %s,
                decided_by = %s,
                decided_at = now(),
                decision_reason = %s,
                request_version = request_version + 1,
                updated_at = now()
            where id = %s
            returning *
            """,
            (decision.value, actor_id, reason[:500], approval["id"]),
        ).fetchone()
        assert updated is not None
        return self._summary(updated)

    def resume_approved_task(self, *, approval: dict[str, Any], actor_id: str) -> None:
        invocation = self.conn.execute(
            """
            select id, tenant_id, workspace_id, run_id, task_id, action_hash, status
            from tool_invocations
            where id = %s and action_hash = %s
            for update
            """,
            (approval["tool_invocation_id"], approval["action_hash"]),
        ).fetchone()
        if invocation is None:
            raise ProblemError(
                409,
                "approval_binding_mismatch",
                "Approved action no longer exists.",
            )
        task = self.conn.execute(
            """
            select t.id, t.status, r.status as run_status
            from tasks t
            join runs r on r.id = t.run_id
            where t.id = %s and t.run_id = %s
            for update
            """,
            (approval["task_id"], approval["run_id"]),
        ).fetchone()
        if task is None or str(task["run_status"]) != "running":
            raise ProblemError(409, "approval_run_not_running", "The run is no longer executable.")
        if str(task["status"]) != "waiting_approval":
            raise ProblemError(
                409,
                "approval_task_not_waiting",
                "The task is not waiting for approval.",
            )
        self.conn.execute(
            """
            update tool_invocations
            set status = 'authorized', updated_at = now()
            where id = %s and status = 'approval_required'
            """,
            (approval["tool_invocation_id"],),
        )
        self.conn.execute(
            """
            update tasks
            set status = 'ready', version = version + 1, updated_at = now()
            where id = %s and status = 'waiting_approval'
            """,
            (approval["task_id"],),
        )
        self.events.append(
            tenant_id=str(approval["tenant_id"]),
            workspace_id=str(approval["workspace_id"]),
            run_id=str(approval["run_id"]),
            task_id=str(approval["task_id"]),
            aggregate_type="task",
            aggregate_id=str(approval["task_id"]),
            event_type="task.ready",
            actor_id=actor_id,
            payload={
                "source": "approval_approved",
                "approval_request_id": approval["id"],
                "action_hash": approval["action_hash"],
            },
        )
        self.outbox.add_task_execution_requested(
            tenant_id=str(approval["tenant_id"]),
            workspace_id=str(approval["workspace_id"]),
            run_id=str(approval["run_id"]),
            task_id=str(approval["task_id"]),
            actor_id=actor_id,
        )

    def fail_rejected_task(self, *, approval: dict[str, Any], actor_id: str) -> None:
        safe_reason = str(approval.get("decision_reason") or "Approval rejected.")[:500]
        self.conn.execute(
            """
            update tool_invocations
            set status = 'policy_denied',
                error_type = 'approval_rejected',
                error_message = %s,
                completed_at = now(),
                updated_at = now()
            where id = %s and status = 'approval_required'
            """,
            (safe_reason, approval["tool_invocation_id"]),
        )
        self.conn.execute(
            """
            update tasks
            set status = 'failed',
                last_error_type = 'approval_rejected',
                last_error_message = %s,
                version = version + 1,
                updated_at = now()
            where id = %s and status = 'waiting_approval'
            """,
            (safe_reason, approval["task_id"]),
        )
        self.conn.execute(
            """
            update runs
            set status = 'failed',
                version = version + 1,
                completed_at = now(),
                updated_at = now()
            where id = %s and status = 'running'
            """,
            (approval["run_id"],),
        )
        self.events.append(
            tenant_id=str(approval["tenant_id"]),
            workspace_id=str(approval["workspace_id"]),
            run_id=str(approval["run_id"]),
            task_id=str(approval["task_id"]),
            aggregate_type="task",
            aggregate_id=str(approval["task_id"]),
            event_type="task.failed",
            actor_id=actor_id,
            payload={"action_hash": approval["action_hash"]},
        )

    def expire_pending(self, *, actor_id: str) -> int:
        rows = self.conn.execute(
            """
            update approval_requests
            set status = 'expired',
                updated_at = now(),
                request_version = request_version + 1
            where status = 'pending' and expires_at <= now()
            returning *
            """
        ).fetchall()
        for row in rows:
            approval = self._summary(row)
            self.conn.execute(
                """
                update tool_invocations
                set status = 'policy_denied',
                    error_type = 'approval_expired',
                    error_message = 'Approval request expired before decision.',
                    completed_at = now(),
                    updated_at = now()
                where id = %s and status = 'approval_required'
                """,
                (approval["tool_invocation_id"],),
            )
            self.conn.execute(
                """
                update tasks
                set status = 'failed',
                    last_error_type = 'approval_expired',
                    last_error_message = 'Approval request expired before decision.',
                    version = version + 1,
                    updated_at = now()
                where id = %s and status = 'waiting_approval'
                """,
                (approval["task_id"],),
            )
            self.conn.execute(
                """
                update runs
                set status = 'failed',
                    version = version + 1,
                    completed_at = now(),
                    updated_at = now()
                where id = %s and status = 'running'
                """,
                (approval["run_id"],),
            )
            self.events.append(
                tenant_id=str(approval["tenant_id"]),
                workspace_id=str(approval["workspace_id"]),
                run_id=str(approval["run_id"]),
                task_id=str(approval["task_id"]),
                aggregate_type="approval_request",
                aggregate_id=str(approval["id"]),
                event_type="approval.expired",
                actor_id=actor_id,
                payload={"action_hash": approval["action_hash"]},
            )
        return len(rows)

    def _summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "workspace_id": str(row["workspace_id"]),
            "run_id": str(row["run_id"]),
            "task_id": str(row["task_id"]),
            "tool_invocation_id": str(row["tool_invocation_id"]),
            "tool_version_id": str(row["tool_version_id"]),
            "requester_id": str(row["requester_id"]),
            "action_hash": str(row["action_hash"]),
            "binding_hash": str(row["binding_hash"]),
            "risk": str(row["risk"]),
            "reason": str(row["reason"]),
            "action_summary": row["action_summary"],
            "status": str(row["status"]),
            "request_version": int(row["request_version"]),
            "expires_at": row["expires_at"].isoformat(),
            "decided_by": str(row["decided_by"]) if row["decided_by"] is not None else None,
            "decided_at": row["decided_at"].isoformat() if row["decided_at"] else None,
            "decision_reason": str(row["decision_reason"]) if row["decision_reason"] else None,
            "consumed_at": row["consumed_at"].isoformat() if row["consumed_at"] else None,
            "created_at": row["created_at"].isoformat(),
        }
