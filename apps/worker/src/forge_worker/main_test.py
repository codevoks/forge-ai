from forge_worker.main import health


def test_health_marks_local_queue_execution() -> None:
    assert health() == {
        "status": "ok",
        "service": "worker",
        "execution": "durable-local-queue",
        "external_integrations": "disabled",
        "queue": "forge:work",
    }
