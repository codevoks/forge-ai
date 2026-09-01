import json
from typing import Any

from psycopg import Connection

from forge_api.api.errors import ProblemError
from forge_api.domain.evaluations import (
    PHASE9_CASES,
    PHASE9_SUITE_DESCRIPTION,
    PHASE9_SUITE_NAME,
    PHASE9_SUITE_VERSION,
    EvaluationCaseDefinition,
    EvaluationCaseOutcome,
    EvaluationStatus,
    LangSmithExportStatus,
    MetricRecord,
)
from forge_api.infrastructure.ids import uuid7


class EvaluationRepository:
    def __init__(self, conn: Connection[dict[str, Any]]) -> None:
        self.conn = conn

    def ensure_phase9_suite(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        actor_id: str,
    ) -> dict[str, Any]:
        suite = self.conn.execute(
            """
            select *
            from evaluation_suites
            where tenant_id = %s and workspace_id = %s and name = %s and version = %s
            """,
            (tenant_id, workspace_id, PHASE9_SUITE_NAME, PHASE9_SUITE_VERSION),
        ).fetchone()
        if suite is None:
            suite = self.conn.execute(
                """
                insert into evaluation_suites
                  (id, tenant_id, workspace_id, name, version, description, created_by)
                values (%s, %s, %s, %s, %s, %s, %s)
                returning *
                """,
                (
                    str(uuid7()),
                    tenant_id,
                    workspace_id,
                    PHASE9_SUITE_NAME,
                    PHASE9_SUITE_VERSION,
                    PHASE9_SUITE_DESCRIPTION,
                    actor_id,
                ),
            ).fetchone()
        assert suite is not None
        for case in PHASE9_CASES:
            self.ensure_case(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                suite_id=str(suite["id"]),
                case=case,
            )
        return self._suite_summary(suite)

    def ensure_case(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        suite_id: str,
        case: EvaluationCaseDefinition,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            insert into evaluation_cases
              (id, tenant_id, workspace_id, suite_id, case_key, category, description,
               security_critical, expected_outcome)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (suite_id, case_key)
            do update set
              category = excluded.category,
              description = excluded.description,
              security_critical = excluded.security_critical,
              expected_outcome = excluded.expected_outcome
            returning *
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                suite_id,
                case.key,
                case.category.value,
                case.description,
                case.security_critical,
                json.dumps(case.expected_outcome),
            ),
        ).fetchone()
        assert row is not None
        return self._case_summary(row)

    def create_run(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        suite_id: str,
        actor_id: str,
        provider_path: str,
        engine_matrix: list[str],
        external_integrations: str,
        langsmith_export_mode: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            insert into evaluation_runs
              (id, tenant_id, workspace_id, suite_id, status, provider_path, engine_matrix,
               external_integrations, langsmith_export_mode, config, created_by)
            values (%s, %s, %s, %s, 'running', %s, %s, %s, %s, %s, %s)
            returning *
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                suite_id,
                provider_path,
                json.dumps(engine_matrix),
                external_integrations,
                langsmith_export_mode,
                json.dumps(config),
                actor_id,
            ),
        ).fetchone()
        assert row is not None
        return self._run_summary(row)

    def complete_run(
        self,
        *,
        evaluation_run_id: str,
        status: EvaluationStatus,
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            update evaluation_runs
            set status = %s, summary = %s, completed_at = now()
            where id = %s
            returning *
            """,
            (status.value, json.dumps(summary), evaluation_run_id),
        ).fetchone()
        assert row is not None
        return self._run_summary(row)

    def get_case_by_key(self, *, suite_id: str, case_key: str) -> dict[str, Any]:
        row = self.conn.execute(
            "select * from evaluation_cases where suite_id = %s and case_key = %s",
            (suite_id, case_key),
        ).fetchone()
        if row is None:
            raise ProblemError(500, "evaluation_case_missing", "Evaluation case is missing.")
        return self._case_summary(row)

    def record_case_result(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        evaluation_run_id: str,
        case_id: str,
        outcome: EvaluationCaseOutcome,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            insert into evaluation_case_results
              (id, tenant_id, workspace_id, evaluation_run_id, case_id, case_key, category,
               status, security_critical, provider, engine_kind, metrics, artifacts,
               failure_message)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning *
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                evaluation_run_id,
                case_id,
                outcome.case_key,
                outcome.category.value,
                outcome.status.value,
                outcome.security_critical,
                outcome.provider,
                outcome.engine_kind,
                json.dumps(outcome.metrics),
                json.dumps(outcome.artifacts),
                outcome.failure_message,
            ),
        ).fetchone()
        assert row is not None
        return self._case_result_summary(row)

    def record_metric(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        evaluation_run_id: str,
        case_result_id: str | None,
        metric: MetricRecord,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            insert into metric_values
              (id, tenant_id, workspace_id, evaluation_run_id, case_result_id, metric_name,
               metric_value, unit, provenance)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            returning *
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                evaluation_run_id,
                case_result_id,
                metric.name,
                metric.value,
                metric.unit,
                metric.provenance.value,
            ),
        ).fetchone()
        assert row is not None
        return self._metric_summary(row)

    def record_export(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        evaluation_run_id: str,
        status: LangSmithExportStatus,
        live_export: bool,
        artifact: dict[str, Any],
        error_message: str | None = None,
    ) -> dict[str, Any]:
        row = self.conn.execute(
            """
            insert into evaluation_exports
              (id, tenant_id, workspace_id, evaluation_run_id, exporter, status, live_export,
               artifact, error_message)
            values (%s, %s, %s, %s, 'langsmith', %s, %s, %s, %s)
            returning *
            """,
            (
                str(uuid7()),
                tenant_id,
                workspace_id,
                evaluation_run_id,
                status.value,
                live_export,
                json.dumps(artifact),
                error_message,
            ),
        ).fetchone()
        assert row is not None
        return self._export_summary(row)

    def get_run_for_actor(self, *, actor_id: str, evaluation_run_id: str) -> dict[str, Any]:
        _ = actor_id
        row = self.conn.execute(
            "select * from evaluation_runs where id = %s",
            (evaluation_run_id,),
        ).fetchone()
        if row is None:
            raise ProblemError(
                404,
                "evaluation_run_not_found",
                "The evaluation run was not found.",
            )
        return self._run_with_children(row)

    def list_runs_for_actor(self, *, actor_id: str, workspace_id: str) -> list[dict[str, Any]]:
        _ = actor_id
        rows = self.conn.execute(
            """
            select *
            from evaluation_runs
            where workspace_id = %s
            order by created_at desc
            limit 20
            """,
            (workspace_id,),
        ).fetchall()
        return [self._run_with_children(row) for row in rows]

    def _run_with_children(self, row: dict[str, Any]) -> dict[str, Any]:
        run = self._run_summary(row)
        result_rows = self.conn.execute(
            """
            select *
            from evaluation_case_results
            where evaluation_run_id = %s
            order by case_key
            """,
            (row["id"],),
        ).fetchall()
        metric_rows = self.conn.execute(
            """
            select *
            from metric_values
            where evaluation_run_id = %s
            order by metric_name
            """,
            (row["id"],),
        ).fetchall()
        export_rows = self.conn.execute(
            """
            select *
            from evaluation_exports
            where evaluation_run_id = %s
            order by created_at
            """,
            (row["id"],),
        ).fetchall()
        run["case_results"] = [self._case_result_summary(result) for result in result_rows]
        run["metrics"] = [self._metric_summary(metric) for metric in metric_rows]
        run["exports"] = [self._export_summary(export) for export in export_rows]
        return run

    def _suite_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "workspace_id": str(row["workspace_id"]),
            "name": str(row["name"]),
            "version": int(row["version"]),
            "description": str(row["description"]),
            "created_at": row["created_at"].isoformat(),
        }

    def _case_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "suite_id": str(row["suite_id"]),
            "case_key": str(row["case_key"]),
            "category": str(row["category"]),
            "description": str(row["description"]),
            "security_critical": bool(row["security_critical"]),
            "expected_outcome": row["expected_outcome"],
        }

    def _run_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "workspace_id": str(row["workspace_id"]),
            "suite_id": str(row["suite_id"]),
            "status": str(row["status"]),
            "provider_path": str(row["provider_path"]),
            "engine_matrix": row["engine_matrix"],
            "external_integrations": str(row["external_integrations"]),
            "langsmith_export_mode": str(row["langsmith_export_mode"]),
            "config": row["config"],
            "summary": row["summary"],
            "created_by": str(row["created_by"]),
            "created_at": row["created_at"].isoformat(),
            "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
        }

    def _case_result_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "evaluation_run_id": str(row["evaluation_run_id"]),
            "case_key": str(row["case_key"]),
            "category": str(row["category"]),
            "status": str(row["status"]),
            "security_critical": bool(row["security_critical"]),
            "provider": str(row["provider"]),
            "engine_kind": str(row["engine_kind"]) if row["engine_kind"] else None,
            "metrics": row["metrics"],
            "artifacts": row["artifacts"],
            "failure_message": row["failure_message"],
            "created_at": row["created_at"].isoformat(),
        }

    def _metric_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "evaluation_run_id": str(row["evaluation_run_id"]),
            "case_result_id": str(row["case_result_id"]) if row["case_result_id"] else None,
            "metric_name": str(row["metric_name"]),
            "metric_value": float(row["metric_value"]),
            "unit": str(row["unit"]),
            "provenance": str(row["provenance"]),
            "created_at": row["created_at"].isoformat(),
        }

    def _export_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "evaluation_run_id": str(row["evaluation_run_id"]),
            "exporter": str(row["exporter"]),
            "status": str(row["status"]),
            "live_export": bool(row["live_export"]),
            "artifact": row["artifact"],
            "error_message": row["error_message"],
            "created_at": row["created_at"].isoformat(),
        }
