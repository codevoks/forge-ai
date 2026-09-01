from typing import Any

import langsmith

from forge_api.config import Settings
from forge_api.domain.evaluations import LangSmithExportStatus


class LangSmithEvaluationExporter:
    """Optional LangSmith seam with a zero-cost local artifact default."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sdk_version = getattr(langsmith, "__version__", "unknown")

    def export(
        self,
        *,
        evaluation_run: dict[str, Any],
        case_results: list[dict[str, Any]],
        metrics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        artifact = {
            "schema": "forge.langsmith.local_eval_export.v1",
            "sdk": {"package": "langsmith", "version": self.sdk_version},
            "evaluation_run_id": evaluation_run["id"],
            "suite_id": evaluation_run["suite_id"],
            "case_keys": [case["case_key"] for case in case_results],
            "metrics": {
                metric["metric_name"]: metric["metric_value"]
                for metric in metrics
                if metric["case_result_id"] is None
            },
            "redaction": (
                "secret references, prompts, raw provider payloads, and bearer tokens excluded"
            ),
        }
        if self.settings.langsmith_export_mode == "disabled":
            return {
                "status": LangSmithExportStatus.DISABLED,
                "live_export": False,
                "artifact": artifact | {"mode": "disabled"},
                "error_message": None,
            }
        if self.settings.langsmith_export_mode == "local":
            return {
                "status": LangSmithExportStatus.LOCAL_ARTIFACT,
                "live_export": False,
                "artifact": artifact | {"mode": "local"},
                "error_message": None,
            }
        if (
            self.settings.external_integrations != "enabled"
            or not self.settings.langsmith_api_key
        ):
            return {
                "status": LangSmithExportStatus.BLOCKED,
                "live_export": False,
                "artifact": artifact | {"mode": "enabled"},
                "error_message": (
                    "LangSmith export requires explicit external integration opt-in and "
                    "a LangSmith API key."
                ),
            }
        return {
            "status": LangSmithExportStatus.BLOCKED,
            "live_export": False,
            "artifact": artifact | {"mode": "enabled"},
            "error_message": (
                "Live LangSmith export is intentionally deferred until a funded endpoint "
                "and benchmarked payload contract are approved."
            ),
        }
