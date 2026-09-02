from collections.abc import Mapping
from contextlib import AbstractContextManager
from typing import Any, Protocol


class TelemetryPort(Protocol):
    def span(
        self,
        name: str,
        *,
        attributes: Mapping[str, Any] | None = None,
        parent_trace_context: Mapping[str, str] | None = None,
    ) -> AbstractContextManager[dict[str, str]]:
        """Open a span for the duration of the block; yields W3C trace context
        (``traceparent`` and, if present, ``tracestate``) usable by
        ``EventRepository.append`` for cross-cutting event correlation."""
        raise NotImplementedError

    def record_exception(self, exc: BaseException) -> None:
        raise NotImplementedError
