import json
from typing import Any

from psycopg import Connection

from forge_api.api.errors import ProblemError
from forge_api.domain.workflow import (
    TASK_TRANSITIONS,
    ReadinessEvaluator,
    RunStatus,
    TaskStatus,
    validate_transition,
)
from forge_api.infrastructure.ids import uuid7


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

    def create_run(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        actor_id: str,
        workflow_version: dict[str, Any],
        objective: str,
        constraints: dict[str, Any],
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
              (id, tenant_id, workspace_id, objective_id, workflow_version_id, status, created_by)
            values (%s, %s, %s, %s, %s, 'created', %s)
            returning id, tenant_id, workspace_id, objective_id, workflow_version_id,
                      status, version, created_by, created_at, started_at, completed_at
            """,
            (run_id, tenant_id, workspace_id, objective_id, workflow_version["id"], actor_id),
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
                   r.status, r.version, r.created_by, r.created_at, r.started_at, r.completed_at,
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
            select id, tenant_id, workspace_id, status
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
