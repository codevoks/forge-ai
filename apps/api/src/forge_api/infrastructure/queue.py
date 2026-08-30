import json
from typing import Any, cast

from forge_api.domain.reliability import JobEnvelope


class InMemoryQueue:
    def __init__(self) -> None:
        self.messages: list[JobEnvelope] = []
        self.acked: set[str] = set()

    def publish(self, envelope: JobEnvelope) -> None:
        self.messages.append(envelope)

    def consume(self, *, consumer_name: str, block_ms: int = 1000) -> JobEnvelope | None:
        _ = consumer_name
        _ = block_ms
        for envelope in self.messages:
            if envelope.message_id not in self.acked:
                return envelope
        return None

    def ack(self, *, message_id: str) -> None:
        self.acked.add(message_id)


class RedisStreamQueue:
    def __init__(self, *, redis_url: str, stream_name: str, group_name: str) -> None:
        try:
            from redis import Redis
            from redis.exceptions import ResponseError
        except ImportError as exc:  # pragma: no cover - startup guard
            raise RuntimeError("redis package is required for RedisStreamQueue") from exc

        self.redis = Redis.from_url(redis_url, decode_responses=True)
        self.response_error = ResponseError
        self.stream_name = stream_name
        self.group_name = group_name
        self._redis_ids_by_message_id: dict[str, str] = {}
        self._ensure_group()

    def _ensure_group(self) -> None:
        try:
            self.redis.xgroup_create(
                self.stream_name,
                self.group_name,
                id="0",
                mkstream=True,
            )
        except self.response_error as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def publish(self, envelope: JobEnvelope) -> None:
        fields: dict[str, str] = {
            "message_id": envelope.message_id,
            "message_type": envelope.message_type,
            "tenant_id": envelope.tenant_id,
            "workspace_id": envelope.workspace_id,
            "aggregate_type": envelope.aggregate_type,
            "aggregate_id": envelope.aggregate_id,
            "payload": json.dumps(envelope.payload, sort_keys=True),
        }
        self.redis.xadd(envelope.stream_name, cast(Any, fields))

    def consume(self, *, consumer_name: str, block_ms: int = 1000) -> JobEnvelope | None:
        response: Any = self.redis.xreadgroup(
            self.group_name,
            consumer_name,
            {self.stream_name: ">"},
            count=1,
            block=block_ms,
        )
        if not response:
            return None
        stream_name, messages = response[0]
        redis_message_id, fields = messages[0]
        payload = json.loads(str(fields.get("payload", "{}")))
        self._redis_ids_by_message_id[str(fields["message_id"])] = str(redis_message_id)
        return JobEnvelope(
            message_id=str(fields["message_id"]),
            message_type=str(fields["message_type"]),
            stream_name=str(stream_name),
            tenant_id=str(fields["tenant_id"]),
            workspace_id=str(fields["workspace_id"]),
            aggregate_type=str(fields["aggregate_type"]),
            aggregate_id=str(fields["aggregate_id"]),
            payload=payload,
        )

    def ack(self, *, message_id: str) -> None:
        redis_message_id = self._redis_ids_by_message_id.pop(message_id, None)
        if redis_message_id is not None:
            self.redis.xack(self.stream_name, self.group_name, redis_message_id)
