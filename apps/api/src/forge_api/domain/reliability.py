from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol


@dataclass(frozen=True)
class JobEnvelope:
    message_id: str
    message_type: str
    stream_name: str
    tenant_id: str
    workspace_id: str
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RetryDecision:
    retryable: bool
    next_retry_at: datetime | None
    reason: str


class Clock(Protocol):
    def now(self) -> datetime:
        raise NotImplementedError


class JitterSource(Protocol):
    def randint(self, lower: int, upper: int) -> int:
        raise NotImplementedError


class SystemClock:
    def now(self) -> datetime:
        return datetime.now().astimezone()


class DeterministicJitter:
    def randint(self, lower: int, upper: int) -> int:
        return lower if lower <= upper else upper


class RetryPolicy:
    def __init__(
        self,
        *,
        max_attempts: int = 3,
        base_delay_seconds: int = 1,
        max_delay_seconds: int = 30,
        jitter: JitterSource | None = None,
    ) -> None:
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.jitter = jitter or DeterministicJitter()

    def decide(self, *, attempt_number: int, error_type: str, now: datetime) -> RetryDecision:
        if error_type == "permanent":
            return RetryDecision(False, None, "permanent_failure")
        if attempt_number >= self.max_attempts:
            return RetryDecision(False, None, "attempts_exhausted")

        upper = min(
            self.max_delay_seconds,
            self.base_delay_seconds * (2 ** max(attempt_number - 1, 0)),
        )
        delay = self.jitter.randint(0, upper)
        return RetryDecision(True, now + timedelta(seconds=delay), "retry_scheduled")


def sanitize_payload(payload: dict[str, Any], *, max_string_length: int = 200) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        normalized_key = str(key)
        if "secret" in normalized_key.lower() or "token" in normalized_key.lower():
            sanitized[normalized_key] = "[redacted]"
        elif isinstance(value, str):
            sanitized[normalized_key] = value[:max_string_length]
        elif isinstance(value, int | float | bool) or value is None:
            sanitized[normalized_key] = value
        elif isinstance(value, dict):
            sanitized[normalized_key] = sanitize_payload(value, max_string_length=max_string_length)
        else:
            sanitized[normalized_key] = str(value)[:max_string_length]
    return sanitized
