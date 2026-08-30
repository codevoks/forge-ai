from typing import Protocol

from forge_api.domain.reliability import JobEnvelope


class QueuePort(Protocol):
    def publish(self, envelope: JobEnvelope) -> None:
        raise NotImplementedError

    def consume(self, *, consumer_name: str, block_ms: int = 1000) -> JobEnvelope | None:
        raise NotImplementedError

    def ack(self, *, message_id: str) -> None:
        raise NotImplementedError
