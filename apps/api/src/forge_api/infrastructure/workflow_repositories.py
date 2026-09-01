import json
from typing import Any

from psycopg import Connection

from forge_api.api.errors import ProblemError
from forge_api.domain.reliability import JobEnvelope, RetryPolicy, sanitize_payload
from forge_api.domain.workflow import (
    TASK_TRANSITIONS,
    ReadinessEvaluator,
    RunStatus,
    TaskStatus,
    validate_transition,
)
from forge_api.infrastructure.ids import uuid7
from forge_api.infrastructure.tool_repositories import RunToolGrantRepository


class EventRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def append(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        run_id: str | None,
        task_id: str | None,
        aggregate_type: str,
        aggregate_id: str,
        event_type: str,
        actor_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            select coalesce(max(sequence), 0) + 1 as sequence
            from execution_events
            where tenant_id = %s and run_id is not distinct from %s
            """,
            (tenant_id, run_id),
        ).fetchone()
        sequence = int(row["sequence"] if row is not None else 1)
        event = self.conn.execute(
            """
            insert into execution_events
              (id, tenant_id, workspace_id, run_id, task_id, aggregate_type, aggregate_id,
               event_type, sequence, actor_id, correlation_id, payload)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning id, sequence, event_type, payload, created_at
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                run_id,
                task_id,
                aggregate_type,
                aggregate_id,
                event_type,
                sequence,
                actor_id,
                str(uuid7()),
                json.dumps(payload),
            ),
        ).fetchone()
        assert event is not None
        return event


class OutboxRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def add_task_execution_requested(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        run_id: str,
        task_id: str,
        actor_id: str,
        stream_name: str = "forge:work",
    ) -> dict[str, Any] | None:
        return self.conn.execute(
            """
            insert into outbox_messages
              (id, tenant_id, workspace_id, aggregate_type, aggregate_id, message_type,
               stream_name, partition_key, payload)
            values (%s, %s, %s, 'task', %s, 'task.execute.requested', %s, %s, %s)
            on conflict do nothing
            returning id, tenant_id, workspace_id, aggregate_type, aggregate_id, message_type,
                      stream_name, partition_key, payload
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                task_id,
                stream_name,
                f"{tenant_id}:{run_id}",
                json.dumps({"run_id": run_id, "task_id": task_id, "actor_id": actor_id}),
            ),
        ).fetchone()

    def due_unpublished(self, *, limit: int = 50) -> list[JobEnvelope]:
        rows = self.conn.execute(
            """
            select id, tenant_id, workspace_id, aggregate_type, aggregate_id, message_type,
                   stream_name, payload
            from outbox_messages
            where published_at is null and available_at <= now()
              and (
                message_type <> 'task.execute.requested'
                or exists (
                  select 1
                  from tasks t
                  join runs r on r.id = t.run_id
                  where t.id = outbox_messages.aggregate_id
                    and t.run_id = (outbox_messages.payload->>'run_id')::uuid
                    and r.status = 'running'
                    and t.status in ('ready', 'retry_wait')
                )
              )
            order by created_at
            limit %s
            for update skip locked
            """,
            (limit,),
        ).fetchall()
        return [
            JobEnvelope(
                message_id=str(row["id"]),
                message_type=str(row["message_type"]),
                stream_name=str(row["stream_name"]),
                tenant_id=str(row["tenant_id"]),
                workspace_id=str(row["workspace_id"]),
                aggregate_type=str(row["aggregate_type"]),
                aggregate_id=str(row["aggregate_id"]),
                payload=row["payload"],
            )
            for row in rows
        ]

    def mark_published(self, *, message_id: str) -> None:
        self.conn.execute(
            """
            update outbox_messages
            set published_at = now(), attempts = attempts + 1, last_error = null
            where id = %s
            """,
            (message_id,),
        )

    def mark_failed_publish(self, *, message_id: str, error: str) -> None:
        self.conn.execute(
            """
            update outbox_messages
            set attempts = attempts + 1, last_error = %s
            where id = %s
            """,
            (error[:500], message_id),
        )


class WorkflowRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def workspace_scope_for_actor(
        self, *, actor_id: str, workspace_id: str
    ) -> dict[str, Any] | None:
        return self.conn.execute(
            """
            select w.id as workspace_id, w.tenant_id, m.role
            from workspaces w
            join memberships m on m.workspace_id = w.id and m.tenant_id = w.tenant_id
            where w.id = %s and m.user_id = %s
            """,
            (workspace_id, actor_id),
        ).fetchone()

    def create_published_version(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        actor_id: str,
        name: str,
        steps: list[dict[str, Any]],
        edges: list[dict[str, str]],
    ) -> dict[str, Any]:
        template_id = str(uuid7())
        version_id = str(uuid7())
        self.conn.execute(
            """
            insert into workflow_templates (id, tenant_id, workspace_id, name, created_by)
            values (%s, %s, %s, %s, %s)
            """,
            (template_id, tenant_id, workspace_id, name, actor_id),
        )
        version = self.conn.execute(
            """
            insert into workflow_versions
              (id, tenant_id, workspace_id, template_id, version_number, status, name, created_by)
            values (%s, %s, %s, %s, 1, 'published', %s, %s)
            returning id, tenant_id, workspace_id, template_id, version_number,
                      status, name, schema_version
            """,
            (version_id, tenant_id, workspace_id, template_id, name, actor_id),
        ).fetchone()
        assert version is not None

        for step in steps:
            self.conn.execute(
                """
                insert into workflow_steps
                  (id, tenant_id, workspace_id, workflow_version_id, step_key, name, kind, input)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid7()),
                    tenant_id,
                    workspace_id,
                    version_id,
                    step["key"],
                    step["name"],
                    step["kind"],
                    json.dumps(step.get("input", {})),
                ),
            )
        for edge in edges:
            self.conn.execute(
                """
                insert into workflow_edges
                  (id, tenant_id, workspace_id, workflow_version_id, from_step_key, to_step_key)
                values (%s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid7()),
                    tenant_id,
                    workspace_id,
                    version_id,
                    edge["from"],
                    edge["to"],
                ),
            )
        return self.get_version_for_actor(actor_id=actor_id, version_id=version_id)

    def list_versions_for_actor(self, *, actor_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            select distinct v.id, v.tenant_id, v.workspace_id, v.template_id, v.version_number,
                   v.status, v.name, v.schema_version
            from workflow_versions v
            join memberships m on m.workspace_id = v.workspace_id and m.tenant_id = v.tenant_id
            where m.user_id = %s
            order by v.name
            """,
            (actor_id,),
        ).fetchall()
        return [self._hydrate_version(row) for row in rows]

    def get_version_for_actor(self, *, actor_id: str, version_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            """
            select v.id, v.tenant_id, v.workspace_id, v.template_id, v.version_number,
                   v.status, v.name, v.schema_version
            from workflow_versions v
            join memberships m on m.workspace_id = v.workspace_id and m.tenant_id = v.tenant_id
            where v.id = %s and m.user_id = %s
            """,
            (version_id, actor_id),
        ).fetchone()
        if row is None:
            raise ProblemError(
                404, "workflow_version_not_found", "The workflow version was not found."
            )
        return self._hydrate_version(row)

    def _hydrate_version(self, row: dict[str, Any]) -> dict[str, Any]:
        steps = self.conn.execute(
            """
            select step_key, name, kind, input
            from workflow_steps
            where workflow_version_id = %s
            order by step_key
            """,
            (row["id"],),
        ).fetchall()
        edges = self.conn.execute(
            """
            select from_step_key, to_step_key
            from workflow_edges
            where workflow_version_id = %s
            order by from_step_key, to_step_key
            """,
            (row["id"],),
        ).fetchall()
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "workspace_id": str(row["workspace_id"]),
            "template_id": str(row["template_id"]),
            "version_number": int(row["version_number"]),
            "status": str(row["status"]),
            "name": str(row["name"]),
            "schema_version": int(row["schema_version"]),
            "steps": [
                {
                    "key": str(step["step_key"]),
                    "name": str(step["name"]),
                    "kind": str(step["kind"]),
                    "input": step["input"],
                }
                for step in steps
            ],
            "edges": [
                {"from": str(edge["from_step_key"]), "to": str(edge["to_step_key"])}
                for edge in edges
            ],
        }


class RunRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn
        self.events = EventRepository(conn)
        self.outbox = OutboxRepository(conn)

    def create_run(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        actor_id: str,
        workflow_version: dict[str, Any],
        objective: str,
        constraints: dict[str, Any],
        engine_kind: str = "custom",
        engine_version: str = "custom-agent-v1",
        engine_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        objective_id = str(uuid7())
        run_id = str(uuid7())
        self.conn.execute(
            """
            insert into objectives
              (id, tenant_id, workspace_id, created_by, objective, constraints)
            values (%s, %s, %s, %s, %s, %s)
            """,
            (objective_id, tenant_id, workspace_id, actor_id, objective, json.dumps(constraints)),
        )
        run = self.conn.execute(
            """
            insert into runs
              (id, tenant_id, workspace_id, objective_id, workflow_version_id, status,
               engine_kind, engine_version, engine_metadata, created_by)
            values (%s, %s, %s, %s, %s, 'created', %s, %s, %s, %s)
            returning id, tenant_id, workspace_id, objective_id, workflow_version_id,
                      status, engine_kind, engine_version, engine_metadata, version, created_by,
                      created_at, started_at, completed_at
            """,
            (
                run_id,
                tenant_id,
                workspace_id,
                objective_id,
                workflow_version["id"],
                engine_kind,
                engine_version,
                json.dumps(engine_metadata or {}),
                actor_id,
            ),
        ).fetchone()
        assert run is not None
        task_ids: dict[str, str] = {}
        for step in workflow_version["steps"]:
            task_id = str(uuid7())
            task_ids[str(step["key"])] = task_id
            self.conn.execute(
                """
                insert into tasks
                  (id, tenant_id, workspace_id, run_id, workflow_version_id, step_key,
                   name, kind, input, status)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending')
                """,
                (
                    task_id,
                    tenant_id,
                    workspace_id,
                    run_id,
                    workflow_version["id"],
                    step["key"],
                    step["name"],
                    step["kind"],
                    json.dumps(step.get("input", {})),
                ),
            )
        for edge in workflow_version["edges"]:
            self.conn.execute(
                """
                insert into task_dependencies
                  (id, tenant_id, workspace_id, run_id, from_task_id, to_task_id,
                   from_step_key, to_step_key)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    str(uuid7()),
                    tenant_id,
                    workspace_id,
                    run_id,
                    task_ids[str(edge["from"])],
                    task_ids[str(edge["to"])],
                    edge["from"],
                    edge["to"],
                ),
            )
        RunToolGrantRepository(self.conn).grant_tools_for_run(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run_id,
            actor_id=actor_id,
            workflow_version=workflow_version,
        )
        self.events.append(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run_id,
            task_id=None,
            aggregate_type="run",
            aggregate_id=run_id,
            event_type="run.created",
            actor_id=actor_id,
            payload={"workflow_version_id": workflow_version["id"], "objective_id": objective_id},
        )
        self._start_run(
            run_id=run_id, tenant_id=tenant_id, workspace_id=workspace_id, actor_id=actor_id
        )
        self.mark_newly_ready_tasks(run_id=run_id, actor_id=actor_id)
        return self.get_run_for_actor(actor_id=actor_id, run_id=run_id)

    def _start_run(self, *, run_id: str, tenant_id: str, workspace_id: str, actor_id: str) -> None:
        self.conn.execute(
            """
            update runs
            set status = 'running',
                version = version + 1,
                started_at = coalesce(started_at, now()),
                updated_at = now()
            where id = %s and status = 'created'
            """,
            (run_id,),
        )
        self.events.append(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            run_id=run_id,
            task_id=None,
            aggregate_type="run",
            aggregate_id=run_id,
            event_type="run.running",
            actor_id=actor_id,
            payload={},
        )

    def list_runs_for_actor(self, *, actor_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            select distinct r.id
            from runs r
            join memberships m on m.workspace_id = r.workspace_id and m.tenant_id = r.tenant_id
            where m.user_id = %s
            order by r.id desc
            limit 50
            """,
            (actor_id,),
        ).fetchall()
        return [self.get_run_for_actor(actor_id=actor_id, run_id=str(row["id"])) for row in rows]

    def get_run_for_actor(self, *, actor_id: str, run_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            """
            select r.id, r.tenant_id, r.workspace_id, r.objective_id, r.workflow_version_id,
                   r.status, r.engine_kind, r.engine_version, r.engine_metadata,
                   r.version, r.created_by, r.created_at, r.started_at, r.completed_at,
                   o.objective, v.name as workflow_name
            from runs r
            join objectives o on o.id = r.objective_id
            join workflow_versions v on v.id = r.workflow_version_id
            join memberships m on m.workspace_id = r.workspace_id and m.tenant_id = r.tenant_id
            where r.id = %s and m.user_id = %s
            """,
            (run_id, actor_id),
        ).fetchone()
        if row is None:
            raise ProblemError(404, "run_not_found", "The run was not found.")
        return self._run_summary(row)

    def list_tasks_for_actor(self, *, actor_id: str, run_id: str) -> list[dict[str, Any]]:
        self.get_run_for_actor(actor_id=actor_id, run_id=run_id)
        rows = self.conn.execute(
            """
            select id, tenant_id, workspace_id, run_id, workflow_version_id, step_key,
                   name, kind, input, status, result, version, started_at, completed_at
            from tasks
            where run_id = %s
            order by step_key
            """,
            (run_id,),
        ).fetchall()
        return [self._task_summary(row) for row in rows]

    def list_events_for_actor(self, *, actor_id: str, run_id: str) -> list[dict[str, Any]]:
        self.get_run_for_actor(actor_id=actor_id, run_id=run_id)
        rows = self.conn.execute(
            """
            select id, run_id, task_id, aggregate_type, aggregate_id, event_type, sequence,
                   actor_id, payload, created_at
            from execution_events
            where run_id = %s
            order by sequence
            """,
            (run_id,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "run_id": str(row["run_id"]),
                "task_id": str(row["task_id"]) if row["task_id"] is not None else None,
                "aggregate_type": str(row["aggregate_type"]),
                "aggregate_id": str(row["aggregate_id"]),
                "event_type": str(row["event_type"]),
                "sequence": int(row["sequence"]),
                "actor_id": str(row["actor_id"]),
                "payload": row["payload"],
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]

    def worker_state_for_actor(self, *, actor_id: str) -> dict[str, Any]:
        _ = actor_id
        outbox = self.conn.execute(
            """
            select
              count(*) filter (where published_at is null) as unpublished,
              count(*) filter (where published_at is not null) as published
            from outbox_messages
            """
        ).fetchone()
        attempts = self.conn.execute(
            """
            select status, count(*) as count
            from task_attempts
            group by status
            order by status
            """
        ).fetchall()
        checkpoints = self.conn.execute("select count(*) as count from checkpoints").fetchone()
        dead_letters = self.conn.execute("select count(*) as count from dead_letters").fetchone()
        return {
            "outbox": {
                "unpublished": int(outbox["unpublished"] if outbox else 0),
                "published": int(outbox["published"] if outbox else 0),
            },
            "attempts": {str(row["status"]): int(row["count"]) for row in attempts},
            "checkpoints": int(checkpoints["count"] if checkpoints else 0),
            "dead_letters": int(dead_letters["count"] if dead_letters else 0),
        }

    def list_dead_letters_for_actor(self, *, actor_id: str) -> list[dict[str, Any]]:
        _ = actor_id
        rows = self.conn.execute(
            """
            select id, tenant_id, workspace_id, run_id, task_id, message_id, reason,
                   sanitized_payload, retryable, requeued_at, requeued_by, created_at
            from dead_letters
            order by created_at desc
            limit 100
            """
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "tenant_id": str(row["tenant_id"]),
                "workspace_id": str(row["workspace_id"]),
                "run_id": str(row["run_id"]) if row["run_id"] is not None else None,
                "task_id": str(row["task_id"]) if row["task_id"] is not None else None,
                "message_id": str(row["message_id"]) if row["message_id"] is not None else None,
                "reason": str(row["reason"]),
                "sanitized_payload": row["sanitized_payload"],
                "retryable": bool(row["retryable"]),
                "requeued_at": row["requeued_at"].isoformat()
                if row["requeued_at"] is not None
                else None,
                "requeued_by": str(row["requeued_by"]) if row["requeued_by"] is not None else None,
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]

    def requeue_dead_letter(
        self,
        *,
        actor_id: str,
        dead_letter_id: str,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            select id, tenant_id, workspace_id, run_id, task_id, reason, requeued_at
            from dead_letters
            where id = %s
            for update
            """,
            (dead_letter_id,),
        ).fetchone()
        if row is None:
            raise ProblemError(404, "dead_letter_not_found", "The dead letter was not found.")
        if row["requeued_at"] is not None:
            raise ProblemError(
                409,
                "dead_letter_already_requeued",
                "The dead letter has already been requeued.",
            )
        if row["run_id"] is None or row["task_id"] is None:
            raise ProblemError(
                422,
                "dead_letter_not_requeueable",
                "Only task dead letters can be requeued.",
            )

        self.conn.execute(
            """
            update dead_letters
            set requeued_at = now(), requeued_by = %s
            where id = %s
            """,
            (actor_id, dead_letter_id),
        )
        self.conn.execute(
            """
            update runs
            set status = 'running',
                completed_at = null,
                version = version + 1,
                updated_at = now()
            where id = %s and status = 'failed'
            """,
            (row["run_id"],),
        )
        self.conn.execute(
            """
            update tasks
            set status = 'ready',
                next_retry_at = null,
                last_error_type = null,
                last_error_message = null,
                version = version + 1,
                updated_at = now()
            where id = %s and status = 'failed'
            """,
            (row["task_id"],),
        )
        self.events.append(
            tenant_id=str(row["tenant_id"]),
            workspace_id=str(row["workspace_id"]),
            run_id=str(row["run_id"]),
            task_id=str(row["task_id"]),
            aggregate_type="dead_letter",
            aggregate_id=str(row["id"]),
            event_type="dead_letter.requeued",
            actor_id=actor_id,
            payload=sanitize_payload({"reason": str(row["reason"])}),
        )
        self.outbox.add_task_execution_requested(
            tenant_id=str(row["tenant_id"]),
            workspace_id=str(row["workspace_id"]),
            run_id=str(row["run_id"]),
            task_id=str(row["task_id"]),
            actor_id=actor_id,
        )
        return self.get_run_for_actor(actor_id=actor_id, run_id=str(row["run_id"]))

    def mark_newly_ready_tasks(self, *, run_id: str, actor_id: str) -> list[dict[str, Any]]:
        run_row = self._run_row_for_update(run_id)
        if str(run_row["status"]) != RunStatus.RUNNING.value:
            return []
        tasks = self.conn.execute(
            "select id, step_key, status from tasks where run_id = %s order by step_key for update",
            (run_id,),
        ).fetchall()
        dependencies = self.conn.execute(
            "select from_step_key, to_step_key from task_dependencies where run_id = %s",
            (run_id,),
        ).fetchall()
        ready_keys = ReadinessEvaluator().ready_task_keys(tasks=tasks, dependencies=dependencies)
        updated: list[dict[str, Any]] = []
        for step_key in ready_keys:
            task = next(task for task in tasks if str(task["step_key"]) == step_key)
            validate_transition(
                aggregate="task",
                current=str(task["status"]),
                target=TaskStatus.READY.value,
                table=TASK_TRANSITIONS,
            )
            row = self.conn.execute(
                """
                update tasks
                set status = 'ready', version = version + 1, updated_at = now()
                where id = %s and status = 'pending'
                returning id, tenant_id, workspace_id, run_id, step_key, status
                """,
                (task["id"],),
            ).fetchone()
            if row is None:
                continue
            self.events.append(
                tenant_id=str(row["tenant_id"]),
                workspace_id=str(row["workspace_id"]),
                run_id=str(row["run_id"]),
                task_id=str(row["id"]),
                aggregate_type="task",
                aggregate_id=str(row["id"]),
                event_type="task.ready",
                actor_id=actor_id,
                payload={"step_key": str(row["step_key"])},
            )
            self.outbox.add_task_execution_requested(
                tenant_id=str(row["tenant_id"]),
                workspace_id=str(row["workspace_id"]),
                run_id=str(row["run_id"]),
                task_id=str(row["id"]),
                actor_id=actor_id,
            )
            updated.append(row)
        return updated

    def advance_one_ready_task(self, *, actor_id: str, run_id: str) -> dict[str, Any]:
        run_row = self._run_row_for_update(run_id)
        if str(run_row["status"]) in {
            status.value for status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED)
        }:
            raise ProblemError(409, "run_terminal", "Terminal runs cannot be advanced.")
        task = self.conn.execute(
            """
            select id, tenant_id, workspace_id, run_id, step_key, name, status,
                   coalesce(
                     (
                       select max(attempt_number)
                       from task_attempts
                       where task_id = tasks.id
                     ),
                     0
                   ) + 1
                     as next_attempt_number
            from tasks
            where run_id = %s and status = 'ready'
            order by step_key
            limit 1
            for update skip locked
            """,
            (run_id,),
        ).fetchone()
        if task is None:
            raise ProblemError(409, "no_ready_task", "No ready task is available to advance.")

        validate_transition(
            aggregate="task",
            current=str(task["status"]),
            target=TaskStatus.RUNNING.value,
            table=TASK_TRANSITIONS,
        )
        self.conn.execute(
            """
            update tasks
            set status = 'running',
                version = version + 1,
                started_at = coalesce(started_at, now()),
                updated_at = now()
            where id = %s and status = 'ready'
            """,
            (task["id"],),
        )
        attempt_id = str(uuid7())
        self.conn.execute(
            """
            insert into task_attempts
              (id, tenant_id, workspace_id, run_id, task_id, attempt_number, status)
            values (%s, %s, %s, %s, %s, %s, 'running')
            """,
            (
                attempt_id,
                task["tenant_id"],
                task["workspace_id"],
                task["run_id"],
                task["id"],
                task["next_attempt_number"],
            ),
        )
        self.events.append(
            tenant_id=str(task["tenant_id"]),
            workspace_id=str(task["workspace_id"]),
            run_id=str(task["run_id"]),
            task_id=str(task["id"]),
            aggregate_type="task",
            aggregate_id=str(task["id"]),
            event_type="task.running",
            actor_id=actor_id,
            payload={"step_key": str(task["step_key"]), "attempt_id": attempt_id},
        )

        result = {
            "mode": "deterministic",
            "summary": f"Completed {task['name']} without external side effects.",
        }
        self.conn.execute(
            """
            update task_attempts
            set status = 'succeeded', completed_at = now(), result = %s
            where id = %s and status = 'running'
            """,
            (json.dumps(result), attempt_id),
        )
        self.conn.execute(
            """
            update tasks
            set status = 'succeeded', result = %s, version = version + 1,
                completed_at = now(), updated_at = now()
            where id = %s and status = 'running'
            """,
            (json.dumps(result), task["id"]),
        )
        self.events.append(
            tenant_id=str(task["tenant_id"]),
            workspace_id=str(task["workspace_id"]),
            run_id=str(task["run_id"]),
            task_id=str(task["id"]),
            aggregate_type="task",
            aggregate_id=str(task["id"]),
            event_type="task.succeeded",
            actor_id=actor_id,
            payload={"step_key": str(task["step_key"]), "attempt_id": attempt_id},
        )
        self.mark_newly_ready_tasks(run_id=run_id, actor_id=actor_id)
        self._maybe_succeed_run(run_id=run_id, actor_id=actor_id)
        return self.get_run_for_actor(actor_id=actor_id, run_id=run_id)

    def cancel_run(self, *, actor_id: str, run_id: str, reason: str) -> dict[str, Any]:
        run_row = self._run_row_for_update(run_id)
        if str(run_row["status"]) in {
            status.value for status in (RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED)
        }:
            return self.get_run_for_actor(actor_id=actor_id, run_id=run_id)

        self.conn.execute(
            """
            update runs
            set status = 'cancelled',
                version = version + 1,
                cancellation_requested_at = now(),
                cancellation_reason = %s,
                cancelled_by = %s,
                completed_at = now(),
                updated_at = now()
            where id = %s and status in ('created', 'running')
            """,
            (reason[:500], actor_id, run_id),
        )
        self.conn.execute(
            """
            update tasks
            set status = 'cancelled', version = version + 1, updated_at = now()
            where run_id = %s and status in ('pending', 'ready', 'retry_wait')
            """,
            (run_id,),
        )
        self.events.append(
            tenant_id=str(run_row["tenant_id"]),
            workspace_id=str(run_row["workspace_id"]),
            run_id=run_id,
            task_id=None,
            aggregate_type="run",
            aggregate_id=run_id,
            event_type="run.cancelled",
            actor_id=actor_id,
            payload={"reason": reason[:500]},
        )
        return self.get_run_for_actor(actor_id=actor_id, run_id=run_id)

    def _maybe_succeed_run(self, *, run_id: str, actor_id: str) -> None:
        run_row = self._run_row_for_update(run_id)
        if str(run_row["status"]) != RunStatus.RUNNING.value:
            return
        rows = self.conn.execute(
            "select status from tasks where run_id = %s",
            (run_id,),
        ).fetchall()
        if rows and all(str(row["status"]) == TaskStatus.SUCCEEDED.value for row in rows):
            self.conn.execute(
                """
                update runs
                set status = 'succeeded',
                    version = version + 1,
                    completed_at = now(),
                    updated_at = now()
                where id = %s and status = 'running'
                """,
                (run_id,),
            )
            self.events.append(
                tenant_id=str(run_row["tenant_id"]),
                workspace_id=str(run_row["workspace_id"]),
                run_id=run_id,
                task_id=None,
                aggregate_type="run",
                aggregate_id=run_id,
                event_type="run.succeeded",
                actor_id=actor_id,
                payload={},
            )

    def _run_row_for_update(self, run_id: str) -> dict[str, Any]:
        row = self.conn.execute(
            """
            select id, tenant_id, workspace_id, status, engine_kind, engine_version,
                   engine_metadata
            from runs
            where id = %s
            for update
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            raise ProblemError(404, "run_not_found", "The run was not found.")
        return row

    def _run_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "workspace_id": str(row["workspace_id"]),
            "objective_id": str(row["objective_id"]),
            "workflow_version_id": str(row["workflow_version_id"]),
            "workflow_name": str(row["workflow_name"]),
            "objective": str(row["objective"]),
            "status": str(row["status"]),
            "engine_kind": str(row.get("engine_kind", "custom")),
            "engine_version": str(row.get("engine_version", "custom-agent-v1")),
            "engine_metadata": row.get("engine_metadata", {}),
            "version": int(row["version"]),
            "created_by": str(row["created_by"]),
            "created_at": row["created_at"].isoformat(),
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        }

    def _task_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "workspace_id": str(row["workspace_id"]),
            "run_id": str(row["run_id"]),
            "workflow_version_id": str(row["workflow_version_id"]),
            "step_key": str(row["step_key"]),
            "name": str(row["name"]),
            "kind": str(row["kind"]),
            "input": row["input"],
            "status": str(row["status"]),
            "result": row["result"],
            "version": int(row["version"]),
            "started_at": row["started_at"].isoformat() if row["started_at"] else None,
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        }


class WorkerRepository:
    def __init__(
        self,
        conn: Connection[dict[str, Any]],
        *,
        lease_seconds: int = 30,
        max_attempts: int = 3,
    ) -> None:
        self.conn = conn
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.events = EventRepository(conn)
        self.outbox = OutboxRepository(conn)

    def begin_inbox(self, *, envelope: JobEnvelope, handler_name: str) -> bool:
        row = self.conn.execute(
            """
            insert into inbox_messages
              (id, tenant_id, workspace_id, message_id, handler_name, status)
            values (%s, %s, %s, %s, %s, 'processing')
            on conflict do nothing
            returning id
            """,
            (
                str(uuid7()),
                envelope.tenant_id,
                envelope.workspace_id,
                envelope.message_id,
                handler_name,
            ),
        ).fetchone()
        if row is not None:
            return True
        existing = self.conn.execute(
            """
            select status from inbox_messages
            where message_id = %s and handler_name = %s
            """,
            (envelope.message_id, handler_name),
        ).fetchone()
        return existing is not None and str(existing["status"]) != "succeeded"

    def finish_inbox(self, *, envelope: JobEnvelope, handler_name: str, status: str) -> None:
        self.conn.execute(
            """
            update inbox_messages
            set status = %s, completed_at = now()
            where message_id = %s and handler_name = %s
            """,
            (status, envelope.message_id, handler_name),
        )

    def claim_task(
        self,
        *,
        envelope: JobEnvelope,
        worker_id: str,
        actor_id: str,
    ) -> dict[str, Any] | None:
        if envelope.message_type != "task.execute.requested":
            return None

        run_id = str(envelope.payload["run_id"])
        task_id = str(envelope.payload["task_id"])
        run_row = self.conn.execute(
            """
            select id, status, cancellation_requested_at, engine_kind, engine_version,
                   engine_metadata
            from runs
            where id = %s and tenant_id = %s and workspace_id = %s
            for update
            """,
            (run_id, envelope.tenant_id, envelope.workspace_id),
        ).fetchone()
        if run_row is None or str(run_row["status"]) != RunStatus.RUNNING.value:
            return None
        if run_row["cancellation_requested_at"] is not None:
            self._cancel_task(task_id=task_id, actor_id=worker_id)
            return None

        task = self.conn.execute(
            """
            select id, tenant_id, workspace_id, run_id, step_key, name, kind, input, status,
                   coalesce(
                     (
                       select max(attempt_number)
                       from task_attempts
                       where task_id = tasks.id
                     ),
                     0
                   ) + 1 as next_attempt_number
            from tasks
            where id = %s and run_id = %s and status = 'ready'
            for update
            """,
            (task_id, run_id),
        ).fetchone()
        if task is None:
            return None

        fencing_token = str(uuid7())
        attempt_id = str(uuid7())
        self.conn.execute(
            """
            update tasks
            set status = 'running',
                version = version + 1,
                started_at = coalesce(started_at, now()),
                updated_at = now()
            where id = %s and status = 'ready'
            """,
            (task_id,),
        )
        self.conn.execute(
            """
            insert into task_attempts
              (id, tenant_id, workspace_id, run_id, task_id, attempt_number, status,
               worker_id, fencing_token, lease_expires_at, heartbeat_at)
            values (%s, %s, %s, %s, %s, %s, 'running', %s, %s,
                    now() + (%s || ' seconds')::interval, now())
            """,
            (
                attempt_id,
                task["tenant_id"],
                task["workspace_id"],
                task["run_id"],
                task["id"],
                task["next_attempt_number"],
                worker_id,
                fencing_token,
                self.lease_seconds,
            ),
        )
        self.events.append(
            tenant_id=str(task["tenant_id"]),
            workspace_id=str(task["workspace_id"]),
            run_id=str(task["run_id"]),
            task_id=str(task["id"]),
            aggregate_type="task",
            aggregate_id=str(task["id"]),
            event_type="task.claimed",
            actor_id=actor_id,
            payload={
                "step_key": str(task["step_key"]),
                "attempt_id": attempt_id,
                "worker_id": worker_id,
            },
        )
        return {
            "attempt_id": attempt_id,
            "fencing_token": fencing_token,
            "attempt_number": int(task["next_attempt_number"]),
            "actor_id": actor_id,
            "tenant_id": str(task["tenant_id"]),
            "workspace_id": str(task["workspace_id"]),
            "run_id": str(task["run_id"]),
            "task_id": str(task["id"]),
            "step_key": str(task["step_key"]),
            "name": str(task["name"]),
            "kind": str(task["kind"]),
            "input": task["input"],
            "worker_id": worker_id,
            "engine_kind": str(run_row.get("engine_kind", "custom")),
            "engine_version": str(run_row.get("engine_version", "custom-agent-v1")),
            "engine_metadata": run_row.get("engine_metadata", {}),
        }

    def complete_attempt(
        self,
        *,
        claim: dict[str, Any],
        result: dict[str, Any],
        actor_id: str,
    ) -> bool:
        run = self.conn.execute(
            """
            select status from runs
            where id = %s and tenant_id = %s and workspace_id = %s
            for update
            """,
            (claim["run_id"], claim["tenant_id"], claim["workspace_id"]),
        ).fetchone()
        if run is None or str(run["status"]) != RunStatus.RUNNING.value:
            return False
        attempt = self.conn.execute(
            """
            update task_attempts
            set status = 'succeeded', completed_at = now(), result = %s
            where id = %s
              and fencing_token = %s
              and status = 'running'
              and lease_expires_at > now()
            returning id
            """,
            (json.dumps(result), claim["attempt_id"], claim["fencing_token"]),
        ).fetchone()
        if attempt is None:
            return False

        self.conn.execute(
            """
            update tasks
            set status = 'succeeded',
                result = %s,
                version = version + 1,
                completed_at = now(),
                updated_at = now()
            where id = %s and status = 'running'
            """,
            (json.dumps(result), claim["task_id"]),
        )
        self.conn.execute(
            """
            insert into checkpoints
              (id, tenant_id, workspace_id, run_id, task_id, attempt_id, checkpoint_type, payload)
            values (%s, %s, %s, %s, %s, %s, 'task_result', %s)
            """,
            (
                str(uuid7()),
                claim["tenant_id"],
                claim["workspace_id"],
                claim["run_id"],
                claim["task_id"],
                claim["attempt_id"],
                json.dumps(result),
            ),
        )
        self.events.append(
            tenant_id=str(claim["tenant_id"]),
            workspace_id=str(claim["workspace_id"]),
            run_id=str(claim["run_id"]),
            task_id=str(claim["task_id"]),
            aggregate_type="task",
            aggregate_id=str(claim["task_id"]),
            event_type="task.succeeded",
            actor_id=actor_id,
            payload={"step_key": claim["step_key"], "attempt_id": claim["attempt_id"]},
        )
        RunRepository(self.conn).mark_newly_ready_tasks(
            run_id=str(claim["run_id"]),
            actor_id=actor_id,
        )
        RunRepository(self.conn)._maybe_succeed_run(
            run_id=str(claim["run_id"]),
            actor_id=actor_id,
        )
        return True

    def fail_attempt(
        self,
        *,
        claim: dict[str, Any],
        error_type: str,
        error_message: str,
        actor_id: str,
        retry_policy: RetryPolicy,
    ) -> None:
        now_row = self.conn.execute("select now() as now").fetchone()
        assert now_row is not None
        decision = retry_policy.decide(
            attempt_number=int(claim["attempt_number"]),
            error_type=error_type,
            now=now_row["now"],
        )
        self.conn.execute(
            """
            update task_attempts
            set status = 'failed',
                completed_at = now(),
                error_type = %s,
                error_message = %s,
                retryable = %s
            where id = %s and fencing_token = %s and status = 'running'
            """,
            (
                error_type,
                error_message[:500],
                decision.retryable,
                claim["attempt_id"],
                claim["fencing_token"],
            ),
        )
        if decision.retryable and decision.next_retry_at is not None:
            self.conn.execute(
                """
                update tasks
                set status = 'retry_wait',
                    next_retry_at = %s,
                    last_error_type = %s,
                    last_error_message = %s,
                    version = version + 1,
                    updated_at = now()
                where id = %s and status = 'running'
                """,
                (
                    decision.next_retry_at,
                    error_type,
                    error_message[:500],
                    claim["task_id"],
                ),
            )
            event_type = "task.retry_scheduled"
        else:
            self.conn.execute(
                """
                update tasks
                set status = 'failed',
                    last_error_type = %s,
                    last_error_message = %s,
                    version = version + 1,
                    updated_at = now()
                where id = %s and status = 'running'
                """,
                (error_type, error_message[:500], claim["task_id"]),
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
                (claim["run_id"],),
            )
            self.conn.execute(
                """
                insert into dead_letters
                  (id, tenant_id, workspace_id, run_id, task_id, message_id, reason,
                   sanitized_payload, retryable)
                values (%s, %s, %s, %s, %s, null, %s, %s, false)
                """,
                (
                    str(uuid7()),
                    claim["tenant_id"],
                    claim["workspace_id"],
                    claim["run_id"],
                    claim["task_id"],
                    decision.reason,
                    json.dumps(
                        sanitize_payload({"error_type": error_type, "error_message": error_message})
                    ),
                ),
            )
            event_type = "task.dead_lettered"

        self.events.append(
            tenant_id=str(claim["tenant_id"]),
            workspace_id=str(claim["workspace_id"]),
            run_id=str(claim["run_id"]),
            task_id=str(claim["task_id"]),
            aggregate_type="task",
            aggregate_id=str(claim["task_id"]),
            event_type=event_type,
            actor_id=actor_id,
            payload=sanitize_payload(
                {
                    "step_key": claim["step_key"],
                    "attempt_id": claim["attempt_id"],
                    "error_type": error_type,
                    "reason": decision.reason,
                }
            ),
        )

    def run_recovery_scan(self, *, actor_id: str) -> dict[str, int]:
        expired = self.conn.execute(
            """
            select a.id as attempt_id, a.tenant_id, a.workspace_id, a.run_id, a.task_id,
                   t.step_key, r.created_by
            from task_attempts a
            join tasks t on t.id = a.task_id
            join runs r on r.id = a.run_id
            where a.status = 'running' and a.lease_expires_at <= now()
            order by a.lease_expires_at
            limit 100
            for update skip locked
            """
        ).fetchall()
        for row in expired:
            self.conn.execute(
                "update task_attempts set status = 'abandoned', completed_at = now() where id = %s",
                (row["attempt_id"],),
            )
            self.conn.execute(
                """
                update tasks
                set status = 'ready', version = version + 1, updated_at = now()
                where id = %s and status = 'running'
                """,
                (row["task_id"],),
            )
            self.events.append(
                tenant_id=str(row["tenant_id"]),
                workspace_id=str(row["workspace_id"]),
                run_id=str(row["run_id"]),
                task_id=str(row["task_id"]),
                aggregate_type="task",
                aggregate_id=str(row["task_id"]),
                event_type="task.lease_expired",
                actor_id=str(row["created_by"]),
                payload={"step_key": str(row["step_key"]), "attempt_id": str(row["attempt_id"])},
            )
            self.outbox.add_task_execution_requested(
                tenant_id=str(row["tenant_id"]),
                workspace_id=str(row["workspace_id"]),
                run_id=str(row["run_id"]),
                task_id=str(row["task_id"]),
                actor_id=str(row["created_by"]),
            )

        due_retries = self.conn.execute(
            """
            update tasks
            set status = 'ready',
                next_retry_at = null,
                version = tasks.version + 1,
                updated_at = now()
            from runs r
            where tasks.run_id = r.id
              and tasks.status = 'retry_wait'
              and tasks.next_retry_at <= now()
            returning tasks.id, tasks.tenant_id, tasks.workspace_id, tasks.run_id,
                      tasks.step_key, r.created_by
            """
        ).fetchall()
        for row in due_retries:
            self.events.append(
                tenant_id=str(row["tenant_id"]),
                workspace_id=str(row["workspace_id"]),
                run_id=str(row["run_id"]),
                task_id=str(row["id"]),
                aggregate_type="task",
                aggregate_id=str(row["id"]),
                event_type="task.ready",
                actor_id=str(row["created_by"]),
                payload={"step_key": str(row["step_key"]), "source": "retry_due"},
            )
            self.outbox.add_task_execution_requested(
                tenant_id=str(row["tenant_id"]),
                workspace_id=str(row["workspace_id"]),
                run_id=str(row["run_id"]),
                task_id=str(row["id"]),
                actor_id=str(row["created_by"]),
            )

        ready_without_outbox = self.conn.execute(
            """
            select t.id, t.tenant_id, t.workspace_id, t.run_id, r.created_by
            from tasks t
            join runs r on r.id = t.run_id
            where t.status = 'ready' and r.status = 'running'
              and not exists (
                select 1 from outbox_messages o
                where o.aggregate_id = t.id
                  and o.message_type = 'task.execute.requested'
                  and o.published_at is null
              )
            limit 100
            """
        ).fetchall()
        republished = 0
        for row in ready_without_outbox:
            created = self.outbox.add_task_execution_requested(
                tenant_id=str(row["tenant_id"]),
                workspace_id=str(row["workspace_id"]),
                run_id=str(row["run_id"]),
                task_id=str(row["id"]),
                actor_id=str(row["created_by"]),
            )
            if created is not None:
                republished += 1

        return {
            "expired_leases": len(expired),
            "due_retries": len(due_retries),
            "republished_ready_tasks": republished,
        }

    def _cancel_task(self, *, task_id: str, actor_id: str) -> None:
        row = self.conn.execute(
            """
            update tasks
            set status = 'cancelled', version = version + 1, updated_at = now()
            where id = %s and status in ('ready', 'running', 'retry_wait')
            returning id, tenant_id, workspace_id, run_id, step_key
            """,
            (task_id,),
        ).fetchone()
        if row is None:
            return
        self.events.append(
            tenant_id=str(row["tenant_id"]),
            workspace_id=str(row["workspace_id"]),
            run_id=str(row["run_id"]),
            task_id=str(row["id"]),
            aggregate_type="task",
            aggregate_id=str(row["id"]),
            event_type="task.cancelled",
            actor_id=actor_id,
            payload={"step_key": str(row["step_key"])},
        )
