"""OpenTelemetry-backed `TelemetryPort`: a vendor-neutral instrumentation
layer. The local JSONL exporter is the zero-cost default and is always
attached unless `telemetry_export_mode` is `disabled`; an OTLP exporter
(usable by any OTLP-compatible collector, including a self-hosted Langfuse
or a local Jaeger) is attached only when `telemetry_export_mode == "enabled"`
AND `external_integrations == "enabled"` AND an endpoint is configured —
otherwise no network call is ever attempted. `SimpleSpanProcessor` already
isolates exporter failures from application code (it catches and logs), so
a broken or unreachable exporter never fails the business operation it is
observing.
"""

import json
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Status, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from forge_api.config import Settings
from forge_api.domain.reliability import sanitize_payload


def trace_id_as_correlation_uuid(trace_id: int) -> str:
    """Format an OTel 128-bit trace id as a UUID string so it can be stored
    directly in `execution_events.correlation_id`: every event sharing one
    trace shares one correlation id."""
    return str(UUID(int=trace_id))


def _to_otel_attributes(attributes: Mapping[str, Any]) -> dict[str, str | bool | int | float]:
    sanitized = sanitize_payload(dict(attributes))
    result: dict[str, str | bool | int | float] = {}
    for key, value in sanitized.items():
        if isinstance(value, bool | int | float | str):
            result[key] = value
        else:
            result[key] = json.dumps(value, sort_keys=True, default=str)
    return result


def _parse_otlp_headers(raw: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    for pair in raw.split(","):
        key, _, value = pair.partition("=")
        if key.strip():
            headers[key.strip()] = value.strip()
    return headers


class LocalJSONLSpanExporter(SpanExporter):
    """Zero-cost default: sanitized spans as local JSON lines. Never raises;
    a write failure is reported as `SpanExportResult.FAILURE` and swallowed
    by the calling `SpanProcessor`, so telemetry never blocks execution."""

    def __init__(self, *, path: Path) -> None:
        self.path = path

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                for span in spans:
                    handle.write(json.dumps(_span_to_record(span), sort_keys=True) + "\n")
            return SpanExportResult.SUCCESS
        except OSError:
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        return None


def _span_to_record(span: ReadableSpan) -> dict[str, Any]:
    context = span.get_span_context()
    return {
        "schema": "forge.telemetry.local_span.v1",
        "trace_id": format(context.trace_id, "032x") if context else None,
        "span_id": format(context.span_id, "016x") if context else None,
        "parent_span_id": format(span.parent.span_id, "016x") if span.parent else None,
        "name": span.name,
        "start_time_unix_nano": span.start_time,
        "end_time_unix_nano": span.end_time,
        "status": span.status.status_code.name,
        "attributes": sanitize_payload(dict(span.attributes or {})),
    }


class ForgeTelemetry:
    """Owns one `TracerProvider` and its exporters; construct once per
    process (API app, worker) and pass to collaborators that need spans."""

    def __init__(self, *, settings: Settings) -> None:
        self.settings = settings
        provider = TracerProvider()
        if settings.telemetry_export_mode != "disabled":
            provider.add_span_processor(
                SimpleSpanProcessor(
                    LocalJSONLSpanExporter(path=settings.telemetry_local_export_path)
                )
            )
        if (
            settings.telemetry_export_mode == "enabled"
            and settings.external_integrations == "enabled"
            and settings.telemetry_otlp_endpoint
        ):
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(
                        endpoint=settings.telemetry_otlp_endpoint,
                        headers=_parse_otlp_headers(settings.telemetry_otlp_headers),
                    )
                )
            )
        self._provider = provider
        self._tracer = provider.get_tracer("forge_api")
        self._propagator = TraceContextTextMapPropagator()

    @contextmanager
    def span(
        self,
        name: str,
        *,
        attributes: Mapping[str, Any] | None = None,
        parent_trace_context: Mapping[str, str] | None = None,
    ) -> Iterator[dict[str, str]]:
        otel_attributes = _to_otel_attributes(attributes or {})
        parent_context = (
            self._propagator.extract(dict(parent_trace_context))
            if parent_trace_context
            else None
        )
        with self._tracer.start_as_current_span(
            name, context=parent_context, attributes=otel_attributes
        ) as otel_span:
            carrier: dict[str, str] = {}
            self._propagator.inject(carrier)
            try:
                yield carrier
            except Exception as exc:
                otel_span.record_exception(exc)
                otel_span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise

    def record_exception(self, exc: BaseException) -> None:
        trace.get_current_span().record_exception(exc)

    def shutdown(self) -> None:
        self._provider.shutdown()


class NullTelemetry:
    """No-op `TelemetryPort` default for call sites that do not opt into
    tracing; keeps every pre-Phase-13 `WorkerConsumer`/`RunService` call
    site working unchanged."""

    @contextmanager
    def span(
        self,
        name: str,
        *,
        attributes: Mapping[str, Any] | None = None,
        parent_trace_context: Mapping[str, str] | None = None,
    ) -> Iterator[dict[str, str]]:
        yield {}

    def record_exception(self, exc: BaseException) -> None:
        return None
