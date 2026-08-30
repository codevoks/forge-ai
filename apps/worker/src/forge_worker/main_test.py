from forge_worker.main import health


def test_health_marks_execution_deferred() -> None:
    assert health() == {
        "status": "ok",
        "service": "worker",
        "execution": "deferred-to-phase-3",
        "external_integrations": "disabled",
    }
