"""
Observability: structured JSON logs, metrics and traces that share one trace ID.

- Logs go to stdout as one JSON object per line, always carrying `trace_id` /
  `span_id` when emitted inside a request, and are also exported over OTLP.
- Traces and metrics are exported over OTLP (HTTP) when OTEL_EXPORTER_OTLP_ENDPOINT
  is set (local/dev stack: OpenTelemetry collector -> Tempo / Prometheus / Loki ->
  Grafana, see observability/ and docs/observability.md). Unset, only the JSON logs run.
- Privacy: telemetry never carries personal data. Emails are masked in every log
  line, only ids/counters/enums are put in span attributes and metric labels, and
  request/response bodies and auth headers are never recorded.

Key user journey instrumented by hand: generating the weekly timetable
(`schedule.generate` span, `schedule_generation_total` and
`schedule_generation_duration_seconds` metrics, start/finish log events).
"""

import json
import logging
import os
import re
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from opentelemetry import metrics, trace
from opentelemetry.trace import Status, StatusCode

SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "calendario-backend")

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# Attributes that exist on every LogRecord: anything else was passed via `extra=`
# and is emitted as a structured field.
_STANDARD_RECORD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__
) | {"message", "asctime", "taskName"}

_tracer = trace.get_tracer(SERVICE_NAME)
_meter = metrics.get_meter(SERVICE_NAME)

GENERATION_OUTCOMES = ("generated", "infeasible", "timeout", "error", "internal_error")

schedule_generation_total = _meter.create_counter(
    "schedule_generation",
    unit="1",
    description="Weekly timetable generations by outcome (generated, infeasible, timeout, error, internal_error)",
)
schedule_generation_duration = _meter.create_histogram(
    "schedule_generation_duration",
    unit="s",
    description="Wall-clock duration of a weekly timetable generation",
)


def scrub(text: str) -> str:
    """Mask e-mail addresses so they never reach a log line."""
    return _EMAIL_RE.sub("[email]", text)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, with trace correlation ids."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "service": SERVICE_NAME,
            "message": scrub(record.getMessage()),
        }
        ctx = trace.get_current_span().get_span_context()
        if ctx.is_valid:
            payload["trace_id"] = format(ctx.trace_id, "032x")
            payload["span_id"] = format(ctx.span_id, "016x")
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = scrub(self.formatException(record.exc_info))
        return json.dumps(payload, default=str, ensure_ascii=False)


class _ScrubFilter(logging.Filter):
    """Masks e-mails in records headed for the OTLP exporter (message and exception text)."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = scrub(record.getMessage())
        record.args = ()
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return
    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(JsonFormatter())
    root.addHandler(stdout)
    # Uvicorn installs its own handlers; route its records through the root JSON handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True


def setup_observability(app=None, engine=None) -> bool:
    """Configure logging; plus OTLP export and auto-instrumentation if an endpoint is set.
    Returns True when OTLP export is enabled."""
    configure_logging()
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False

    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({
        "service.name": SERVICE_NAME,
        "deployment.environment.name": os.environ.get("DEPLOY_ENV", "local"),
    })

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    metrics.set_meter_provider(MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=5000)],
    ))

    from opentelemetry._logs import set_logger_provider

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)
    otlp_handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    otlp_handler.addFilter(_ScrubFilter())
    logging.getLogger().addHandler(otlp_handler)

    # Export every outcome series at 0 from startup: a counter that first appears at 1
    # has no earlier sample, so increase() would miss that first failure and the alert
    # would never fire.
    for outcome in GENERATION_OUTCOMES:
        schedule_generation_total.add(0, {"outcome": outcome})

    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        # Request bodies/headers are not recorded by default; /health is noise.
        FastAPIInstrumentor.instrument_app(app, excluded_urls="health")
    if engine is not None:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        SQLAlchemyInstrumentor().instrument(engine=engine)
    return True


@contextmanager
def generation_journey(week_start: str) -> Iterator["_Journey"]:
    """Span + metrics + start/finish log events around one timetable generation."""
    log = logging.getLogger("app.journey.schedule_generate")
    journey = _Journey()
    started = time.perf_counter()
    with _tracer.start_as_current_span("schedule.generate") as span:
        span.set_attribute("schedule.week_start", str(week_start))
        log.info("schedule_generation_started", extra={"event": "schedule_generation_started", "week_start": str(week_start)})
        try:
            yield journey
        except Exception as exc:
            journey.outcome = "internal_error"
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
            raise
        finally:
            duration = time.perf_counter() - started
            span.set_attribute("schedule.outcome", journey.outcome)
            if journey.n_slots is not None:
                span.set_attribute("schedule.n_slots", journey.n_slots)
            if journey.outcome == "internal_error":
                span.set_status(Status(StatusCode.ERROR, "internal_error"))
            schedule_generation_total.add(1, {"outcome": journey.outcome})
            schedule_generation_duration.record(duration, {"outcome": journey.outcome})
            level = logging.ERROR if journey.outcome == "internal_error" else logging.INFO
            log.log(level, "schedule_generation_finished", extra={
                "event": "schedule_generation_finished", "week_start": str(week_start),
                "outcome": journey.outcome, "duration_s": round(duration, 3),
                "n_slots": journey.n_slots,
            })


class _Journey:
    outcome: str = "error"
    n_slots: Optional[int] = None

    def internal_error(self, exc: BaseException) -> None:
        """An unexpected exception the service handled by returning status="error":
        still a user-visible failure, and the one the on-call alert fires on."""
        self.outcome = "internal_error"
        span = trace.get_current_span()
        span.record_exception(exc)
        span.set_status(Status(StatusCode.ERROR, type(exc).__name__))
        logging.getLogger("app.journey.schedule_generate").error(
            "schedule_generation_exception", exc_info=exc,
            extra={"event": "schedule_generation_exception", "exception_type": type(exc).__name__},
        )

    def finish(self, status: str, n_slots: Optional[int] = None) -> None:
        if self.outcome != "internal_error":
            self.outcome = status
        self.n_slots = n_slots
