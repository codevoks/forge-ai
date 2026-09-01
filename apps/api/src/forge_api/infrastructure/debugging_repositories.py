import base64
import json
from hashlib import sha256
from typing import Any

from psycopg import Connection

from forge_api.api.errors import ProblemError
from forge_api.domain.debugging import (
    EVENT_CATALOG,
    PROJECTION_TERMINAL_RUN_EVENTS,
    PROJECTION_TERMINAL_TASK_EVENTS,
    ProjectionStatus,
    ReplayMode,
    ReplayStatus,
    TraceExportStatus,
)
from forge_api.domain.reliability import sanitize_payload
from forge_api.infrastructure.ids import uuid7
from forge_api.infrastructure.workflow_repositories import RunRepository


def encode_event_cursor(*, run_id: str, sequence: int) -> str:
    payload = json.dumps(
        {"run_id": run_id, "sequence": sequence},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii")


def decode_event_cursor(cursor: str, *, expected_run_id: str) -> int:
    try:
        decoded = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        payload = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ProblemError(400, "debug_cursor_invalid", "The event cursor is invalid.") from exc
    if not isinstance(payload, dict) or payload.get("run_id") != expected_run_id:
        raise ProblemError(400, "debug_cursor_invalid", "The event cursor is invalid.")
    sequence = payload.get("sequence")
    if not isinstance(sequence, int) or sequence < 0:
        raise ProblemError(400, "debug_cursor_invalid", "The event cursor is invalid.")
    return sequence


class DebuggerRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def get_run_for_actor(self, *, actor_id: str, run_id: str) -> dict[str, Any]:
        return RunRepository(self.conn).get_run_for_actor(actor_id=actor_id, run_id=run_id)

    def event_feed(
        self,
        *,
        actor_id: str,
        run_id: str,
        after_sequence: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        self.get_run_for_actor(actor_id=actor_id, run_id=run_id)
        bounded_limit = max(1, min(limit, 100))
        rows = self.conn.execute(
            """
            select id, tenant_id, workspace_id, run_id, task_id, aggregate_type, aggregate_id,
                   event_type, sequence, actor_id, causation_id, correlation_id, payload,
                   schema_version, trace_context, sanitized_diff, retention_class, payload_hash,
                   created_at
            from execution_events
            where run_id = %s and sequence > %s
            order by sequence
            limit %s
            """,
            (run_id, after_sequence, bounded_limit + 1),
        ).fetchall()
        visible = rows[:bounded_limit]
        has_more = len(rows) > bounded_limit
        next_sequence = int(visible[-1]["sequence"]) if visible else after_sequence
        return {
            "events": [self._event_summary(row) for row in visible],
            "next_cursor": encode_event_cursor(run_id=run_id, sequence=next_sequence)
            if visible
            else None,
            "has_more": has_more,
        }

    def debugger_snapshot(self, *, actor_id: str, run_id: str) -> dict[str, Any]:
        run = self.get_run_for_actor(actor_id=actor_id, run_id=run_id)
        tasks = RunRepository(self.conn).list_tasks_for_actor(actor_id=actor_id, run_id=run_id)
        feed = self.event_feed(actor_id=actor_id, run_id=run_id, limit=100)
        model_calls = self._model_calls(run_id=run_id)
        tool_invocations = self._tool_invocations(run_id=run_id)
        evidence_items = self._evidence_items(run_id=run_id)
        agent_iterations = self._agent_iterations(run_id=run_id)
        forge_checkpoints = self._forge_checkpoints(run_id=run_id)
        engine_checkpoints = self._engine_checkpoints(run_id=run_id)
        latest_verification = self.latest_projection_verification(run_id=run_id)
        replay_sessions = self.list_replay_sessions(actor_id=actor_id, run_id=run_id)
        trace_exports = self.list_trace_exports(actor_id=actor_id, run_id=run_id)
        return {
            "run": run,
            "tasks": tasks,
            "event_catalog": [
                item.model_dump(mode="json")
                for item in sorted(EVENT_CATALOG.values(), key=lambda schema: schema.event_type)
            ],
            "timeline": feed,
            "model_calls": model_calls,
            "tool_invocations": tool_invocations,
            "evidence_items": evidence_items,
            "agent_iterations": agent_iterations,
            "forge_checkpoints": forge_checkpoints,
            "engine_checkpoints": engine_checkpoints,
            "projection_verification": latest_verification,
            "replay_sessions": replay_sessions,
            "trace_exports": trace_exports,
            "security_posture": {
                "raw_payloads_exposed": False,
                "effect_replay_enabled": False,
                "tenant_scope_revalidated": True,
                "framework_state_authoritative": False,
                "secrets_redacted": True,
            },
        }

    def verify_projection(
        self,
        *,
        actor_id: str,
        tenant_id: str,
        workspace_id: str,
        run_id: str,
    ) -> dict[str, Any]:
        run = self.get_run_for_actor(actor_id=actor_id, run_id=run_id)
        tasks = RunRepository(self.conn).list_tasks_for_actor(actor_id=actor_id, run_id=run_id)
        events = self.event_feed(actor_id=actor_id, run_id=run_id, limit=100)["events"]
        expected_run_status = self._fold_run_status(events)
        expected_task_statuses = self._fold_task_statuses(events)
        actual_task_statuses = {task["id"]: task["status"] for task in tasks}
        mismatches: list[dict[str, Any]] = []
        if expected_run_status != run["status"]:
            mismatches.append(
                {
                    "kind": "run_status",
                    "expected": expected_run_status,
                    "actual": run["status"],
                }
            )
        for task_id, expected_status in expected_task_statuses.items():
            actual_status = actual_task_statuses.get(task_id)
            if actual_status != expected_status:
                mismatches.append(
                    {
                        "kind": "task_status",
                        "task_id": task_id,
                        "expected": expected_status,
                        "actual": actual_status,
                    }
                )
        status = ProjectionStatus.PASSED if not mismatches else ProjectionStatus.FAILED
        row = self.conn.execute(
            """
            insert into debugger_projection_verifications
              (id, tenant_id, workspace_id, run_id, status, checked_event_count,
               expected_run_status, actual_run_status, expected_task_statuses,
               actual_task_statuses, mismatch_count, mismatches, created_by)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning *
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                run_id,
                status.value,
                len(events),
                expected_run_status,
                run["status"],
                json.dumps(expected_task_statuses),
                json.dumps(actual_task_statuses),
                len(mismatches),
                json.dumps(mismatches),
                actor_id,
            ),
        ).fetchone()
        assert row is not None
        return self._projection_summary(row)

    def create_replay_session(
        self,
        *,
        actor_id: str,
        tenant_id: str,
        workspace_id: str,
        run_id: str,
        mode: ReplayMode,
    ) -> dict[str, Any]:
        run = self.get_run_for_actor(actor_id=actor_id, run_id=run_id)
        events = self.event_feed(actor_id=actor_id, run_id=run_id, limit=100)["events"]
        model_calls = self._model_calls(run_id=run_id)
        tool_invocations = self._tool_invocations(run_id=run_id)
        unsafe_invocations = [
            invocation
            for invocation in tool_invocations
            if invocation["risk"] in {"simulated_effect", "external_effect"}
            or invocation["status"] in {"approval_required", "authorized", "outcome_unknown"}
        ]
        policy = {
            "default_mode": "simulation",
            "real_effect_adapters_available": False,
            "reuses_approval": False,
            "uses_current_authorization": True,
            "model_outputs_are_recorded_observations": True,
        }
        if mode == ReplayMode.EFFECT_REPLAY:
            status = ReplayStatus.BLOCKED
            summary = {
                "reason": "effect_replay_disabled",
                "message": "Effect replay is disabled; use simulation/reconstruction only.",
                "blocked_invocations": len(unsafe_invocations),
                "authoritative_state_mutated": False,
            }
        else:
            status = ReplayStatus.PASSED
            summary = {
                "source_run_status": run["status"],
                "observed_events": len(events),
                "observed_model_calls": len(model_calls),
                "observed_tool_invocations": len(tool_invocations),
                "unsafe_effect_invocations_blocked": len(unsafe_invocations),
                "authoritative_state_mutated": False,
                "paid_provider_calls": 0,
                "nondeterminism_note": (
                    "Model replay is comparative; recorded output is not treated "
                    "as deterministic authority."
                ),
            }
        session_id = str(uuid7())
        row = self.conn.execute(
            """
            insert into debugger_replay_sessions
              (id, tenant_id, workspace_id, source_run_id, mode, status, policy,
               summary, created_by, completed_at)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            returning *
            """,
            (
                session_id,
                tenant_id,
                workspace_id,
                run_id,
                mode.value,
                status.value,
                json.dumps(policy),
                json.dumps(summary),
                actor_id,
            ),
        ).fetchone()
        assert row is not None
        artifact_payload = {
            "schema": "forge.debugger.replay_artifact.v1",
            "mode": mode.value,
            "source_run_id": run_id,
            "event_hashes": [
                {"sequence": item["sequence"], "payload_hash": item["payload_hash"]}
                for item in events
            ],
            "model_call_ids": [item["id"] for item in model_calls],
            "tool_action_hashes": [
                {"tool_invocation_id": item["id"], "action_hash": item["action_hash"]}
                for item in tool_invocations
            ],
            "tripwire": {
                "real_effect_adapter_called": False,
                "approval_reused": False,
                "authoritative_state_mutated": False,
            },
        }
        self.conn.execute(
            """
            insert into debugger_replay_artifacts
              (id, tenant_id, workspace_id, replay_session_id, artifact_type, payload)
            values (%s, %s, %s, %s, 'simulation_summary', %s)
            """,
            (str(uuid7()), tenant_id, workspace_id, session_id, json.dumps(artifact_payload)),
        )
        return self.get_replay_session(actor_id=actor_id, replay_session_id=session_id)

    def get_replay_session(self, *, actor_id: str, replay_session_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            """
            select s.*
            from debugger_replay_sessions s
            join memberships m on m.tenant_id = s.tenant_id and m.workspace_id = s.workspace_id
            where s.id = %s and m.user_id = %s
            """,
            (replay_session_id, actor_id),
        ).fetchone()
        if row is None:
            raise ProblemError(404, "replay_session_not_found", "The replay session was not found.")
        return self._replay_summary(row)

    def list_replay_sessions(self, *, actor_id: str, run_id: str) -> list[dict[str, Any]]:
        self.get_run_for_actor(actor_id=actor_id, run_id=run_id)
        rows = self.conn.execute(
            """
            select *
            from debugger_replay_sessions
            where source_run_id = %s
            order by created_at desc
            limit 20
            """,
            (run_id,),
        ).fetchall()
        return [self._replay_summary(row) for row in rows]

    def create_trace_export(
        self,
        *,
        actor_id: str,
        tenant_id: str,
        workspace_id: str,
        run_id: str,
        exporter: str,
        mode: str,
        external_integrations: str,
    ) -> dict[str, Any]:
        self.get_run_for_actor(actor_id=actor_id, run_id=run_id)
        if mode == "enabled" and external_integrations != "enabled":
            status = TraceExportStatus.BLOCKED
            artifact: dict[str, Any] = {
                "schema": "forge.debugger.trace_export.v1",
                "reason": "external_integrations_disabled",
                "live_export": False,
            }
            error_message = "Live telemetry export is disabled in the zero-cost profile."
        elif mode == "disabled":
            status = TraceExportStatus.DISABLED
            artifact = {"schema": "forge.debugger.trace_export.v1", "live_export": False}
            error_message = None
        else:
            feed = self.event_feed(actor_id=actor_id, run_id=run_id, limit=100)
            artifact = {
                "schema": "forge.debugger.trace_export.v1",
                "exporter": exporter,
                "live_export": False,
                "run_id": run_id,
                "event_refs": [
                    {
                        "event_id": event["id"],
                        "sequence": event["sequence"],
                        "event_type": event["event_type"],
                        "payload_hash": event["payload_hash"],
                    }
                    for event in feed["events"]
                ],
                "model_call_refs": [
                    {
                        "model_call_id": call["id"],
                        "provider": call["provider"],
                        "live_provider": call["live_provider"],
                    }
                    for call in self._model_calls(run_id=run_id)
                ],
                "tool_invocation_refs": [
                    {
                        "tool_invocation_id": invocation["id"],
                        "tool_name": invocation["tool_name"],
                        "action_hash": invocation["action_hash"],
                        "status": invocation["status"],
                    }
                    for invocation in self._tool_invocations(run_id=run_id)
                ],
                "langgraph_checkpoint_refs": [
                    {
                        "checkpoint_id": checkpoint["checkpoint_id"],
                        "node_name": checkpoint["node_name"],
                    }
                    for checkpoint in self._engine_checkpoints(run_id=run_id)
                ],
                "paid_provider_calls": 0,
            }
            status = TraceExportStatus.LOCAL_ARTIFACT
            error_message = None
        row = self.conn.execute(
            """
            insert into debugger_trace_exports
              (id, tenant_id, workspace_id, run_id, exporter, status, live_export, artifact,
               error_message, created_by)
            values (%s, %s, %s, %s, %s, %s, false, %s, %s, %s)
            returning *
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                run_id,
                exporter,
                status.value,
                json.dumps(sanitize_payload(artifact)),
                error_message,
                actor_id,
            ),
        ).fetchone()
        assert row is not None
        return self._trace_export_summary(row)

    def list_trace_exports(self, *, actor_id: str, run_id: str) -> list[dict[str, Any]]:
        self.get_run_for_actor(actor_id=actor_id, run_id=run_id)
        rows = self.conn.execute(
            """
            select *
            from debugger_trace_exports
            where run_id = %s
            order by created_at desc
            limit 20
            """,
            (run_id,),
        ).fetchall()
        return [self._trace_export_summary(row) for row in rows]

    def latest_projection_verification(self, *, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            select *
            from debugger_projection_verifications
            where run_id = %s
            order by created_at desc
            limit 1
            """,
            (run_id,),
        ).fetchone()
        return self._projection_summary(row) if row is not None else None

    def _fold_run_status(self, events: list[dict[str, Any]]) -> str:
        status = "created"
        for event in events:
            if event["event_type"] == "run.running":
                status = "running"
            elif event["event_type"] in PROJECTION_TERMINAL_RUN_EVENTS:
                status = PROJECTION_TERMINAL_RUN_EVENTS[event["event_type"]]
        return status

    def _fold_task_statuses(self, events: list[dict[str, Any]]) -> dict[str, str]:
        statuses: dict[str, str] = {}
        for event in events:
            task_id = event.get("task_id")
            if not task_id:
                continue
            if event["event_type"] == "task.ready":
                statuses[str(task_id)] = "ready"
            elif event["event_type"] == "task.claimed":
                statuses[str(task_id)] = "running"
            elif event["event_type"] == "task.retry_scheduled":
                statuses[str(task_id)] = "retry_wait"
            elif event["event_type"] in PROJECTION_TERMINAL_TASK_EVENTS:
                statuses[str(task_id)] = PROJECTION_TERMINAL_TASK_EVENTS[event["event_type"]]
        return statuses

    def _event_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = row["payload"] if isinstance(row["payload"], dict) else {}
        payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        payload_hash = row.get("payload_hash") or sha256(payload_json.encode("utf-8")).hexdigest()
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "workspace_id": str(row["workspace_id"]),
            "run_id": str(row["run_id"]),
            "task_id": str(row["task_id"]) if row["task_id"] is not None else None,
            "aggregate_type": str(row["aggregate_type"]),
            "aggregate_id": str(row["aggregate_id"]),
            "event_type": str(row["event_type"]),
            "schema_version": int(row["schema_version"]),
            "sequence": int(row["sequence"]),
            "actor_id": str(row["actor_id"]),
            "causation_id": str(row["causation_id"]) if row["causation_id"] else None,
            "correlation_id": str(row["correlation_id"]),
            "payload": sanitize_payload(payload),
            "trace_context": sanitize_payload(row["trace_context"]),
            "sanitized_diff": sanitize_payload(row["sanitized_diff"]),
            "retention_class": str(row["retention_class"]),
            "payload_hash": str(payload_hash),
            "catalog_known": str(row["event_type"]) in EVENT_CATALOG,
            "created_at": row["created_at"].isoformat(),
        }

    def _model_calls(self, *, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            select id, provider, model_name, status, request_hash, request_summary,
                   response_summary, error_type, error_message, input_tokens, output_tokens,
                   total_tokens, estimated_cost_minor, latency_ms, live_provider,
                   external_request_id, created_at, completed_at
            from model_calls
            where run_id = %s
            order by created_at
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "provider": str(row["provider"]),
                "model_name": str(row["model_name"]),
                "status": str(row["status"]),
                "request_hash": str(row["request_hash"]),
                "request_summary": sanitize_payload(row["request_summary"]),
                "response_summary": sanitize_payload(row["response_summary"]),
                "error_type": str(row["error_type"]) if row["error_type"] else None,
                "error_message": str(row["error_message"]) if row["error_message"] else None,
                "input_tokens": int(row["input_tokens"]),
                "output_tokens": int(row["output_tokens"]),
                "total_tokens": int(row["total_tokens"]),
                "estimated_cost_minor": int(row["estimated_cost_minor"]),
                "latency_ms": int(row["latency_ms"]),
                "live_provider": bool(row["live_provider"]),
                "external_request_id": str(row["external_request_id"])
                if row["external_request_id"]
                else None,
                "created_at": row["created_at"].isoformat(),
                "completed_at": row["completed_at"].isoformat()
                if row["completed_at"] is not None
                else None,
            }
            for row in rows
        ]

    def _tool_invocations(self, *, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            select id, task_id, attempt_id, tool_name, tool_version, risk, action_hash,
                   idempotency_key, status, input, output, error_type, error_message,
                   provider_operation_id, created_at, completed_at
            from tool_invocations
            where run_id = %s
            order by created_at
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "task_id": str(row["task_id"]),
                "attempt_id": str(row["attempt_id"]) if row["attempt_id"] else None,
                "tool_name": str(row["tool_name"]),
                "tool_version": int(row["tool_version"]),
                "risk": str(row["risk"]),
                "action_hash": str(row["action_hash"]),
                "idempotency_key": str(row["idempotency_key"]),
                "status": str(row["status"]),
                "input": sanitize_payload(row["input"]),
                "output": sanitize_payload(row["output"] or {}),
                "error_type": str(row["error_type"]) if row["error_type"] else None,
                "error_message": str(row["error_message"]) if row["error_message"] else None,
                "provider_operation_id": str(row["provider_operation_id"])
                if row["provider_operation_id"]
                else None,
                "created_at": row["created_at"].isoformat(),
                "completed_at": row["completed_at"].isoformat()
                if row["completed_at"] is not None
                else None,
            }
            for row in rows
        ]

    def _evidence_items(self, *, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            select id, task_id, tool_invocation_id, source_type, source_name, trust_label,
                   summary, content_hash, created_at
            from evidence_items
            where run_id = %s
            order by created_at
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "task_id": str(row["task_id"]) if row["task_id"] else None,
                "tool_invocation_id": str(row["tool_invocation_id"])
                if row["tool_invocation_id"]
                else None,
                "source_type": str(row["source_type"]),
                "source_name": str(row["source_name"]),
                "trust_label": str(row["trust_label"]),
                "summary": sanitize_payload(row["summary"]),
                "content_hash": str(row["content_hash"]),
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]

    def _agent_iterations(self, *, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            select id, task_id, attempt_id, iteration_number, model_call_id, decision_type,
                   decision_status, context_hash, counters_snapshot, decision,
                   validation_errors, result, created_at
            from agent_iterations
            where run_id = %s
            order by iteration_number
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "task_id": str(row["task_id"]),
                "attempt_id": str(row["attempt_id"]),
                "iteration_number": int(row["iteration_number"]),
                "model_call_id": str(row["model_call_id"]),
                "decision_type": str(row["decision_type"]),
                "decision_status": str(row["decision_status"]),
                "context_hash": str(row["context_hash"]),
                "counters_snapshot": sanitize_payload(row["counters_snapshot"]),
                "decision": sanitize_payload(row["decision"]),
                "validation_errors": row["validation_errors"],
                "result": sanitize_payload(row["result"]),
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]

    def _forge_checkpoints(self, *, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            select id, task_id, attempt_id, checkpoint_type, payload, created_at
            from checkpoints
            where run_id = %s
            order by created_at
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "task_id": str(row["task_id"]),
                "attempt_id": str(row["attempt_id"]),
                "checkpoint_type": str(row["checkpoint_type"]),
                "payload": sanitize_payload(row["payload"]),
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]

    def _engine_checkpoints(self, *, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            select id, task_id, attempt_id, engine_kind, engine_version, namespace,
                   checkpoint_id, node_name, state_summary, metadata, created_at
            from workflow_engine_checkpoints
            where run_id = %s
            order by created_at, checkpoint_id
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "task_id": str(row["task_id"]) if row["task_id"] else None,
                "attempt_id": str(row["attempt_id"]) if row["attempt_id"] else None,
                "engine_kind": str(row["engine_kind"]),
                "engine_version": str(row["engine_version"]),
                "namespace": str(row["namespace"]),
                "checkpoint_id": str(row["checkpoint_id"]),
                "node_name": str(row["node_name"]),
                "state_summary": sanitize_payload(row["state_summary"]),
                "metadata": sanitize_payload(row["metadata"]),
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]

    def _projection_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "run_id": str(row["run_id"]),
            "status": str(row["status"]),
            "checked_event_count": int(row["checked_event_count"]),
            "expected_run_status": str(row["expected_run_status"]),
            "actual_run_status": str(row["actual_run_status"]),
            "expected_task_statuses": row["expected_task_statuses"],
            "actual_task_statuses": row["actual_task_statuses"],
            "mismatch_count": int(row["mismatch_count"]),
            "mismatches": row["mismatches"],
            "created_by": str(row["created_by"]),
            "created_at": row["created_at"].isoformat(),
        }

    def _replay_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        artifacts = self.conn.execute(
            """
            select id, artifact_type, payload, created_at
            from debugger_replay_artifacts
            where replay_session_id = %s
            order by created_at
            """,
            (row["id"],),
        ).fetchall()
        return {
            "id": str(row["id"]),
            "source_run_id": str(row["source_run_id"]),
            "mode": str(row["mode"]),
            "status": str(row["status"]),
            "policy": row["policy"],
            "summary": row["summary"],
            "created_by": str(row["created_by"]),
            "created_at": row["created_at"].isoformat(),
            "completed_at": row["completed_at"].isoformat()
            if row["completed_at"] is not None
            else None,
            "artifacts": [
                {
                    "id": str(artifact["id"]),
                    "artifact_type": str(artifact["artifact_type"]),
                    "payload": sanitize_payload(artifact["payload"]),
                    "created_at": artifact["created_at"].isoformat(),
                }
                for artifact in artifacts
            ],
        }

    def _trace_export_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "run_id": str(row["run_id"]),
            "exporter": str(row["exporter"]),
            "status": str(row["status"]),
            "live_export": bool(row["live_export"]),
            "artifact": sanitize_payload(row["artifact"]),
            "error_message": str(row["error_message"]) if row["error_message"] else None,
            "created_by": str(row["created_by"]),
            "created_at": row["created_at"].isoformat(),
        }
