"""Observability: structured logs share the trace ID, PII is masked, and the
timetable-generation journey reports its outcome (the signal the alert fires on)."""

import json
import logging

import pytest
from opentelemetry.sdk.trace import TracerProvider

import app.observability as obs


class _Recorder:
    def __init__(self):
        self.calls = []

    def add(self, value, attributes=None):
        self.calls.append((value, dict(attributes or {})))

    record = add


@pytest.fixture
def metrics_recorder(monkeypatch):
    total, duration = _Recorder(), _Recorder()
    monkeypatch.setattr(obs, "schedule_generation_total", total)
    monkeypatch.setattr(obs, "schedule_generation_duration", duration)
    return total, duration


def _format(message, **extra):
    record = logging.LogRecord("t", logging.INFO, __file__, 1, message, (), None)
    record.__dict__.update(extra)
    return json.loads(obs.JsonFormatter().format(record))


def test_json_log_carries_trace_and_span_id_inside_a_span():
    tracer = TracerProvider().get_tracer("test")
    with tracer.start_as_current_span("request") as span:
        line = _format("hello")
        ctx = span.get_span_context()
    assert line["trace_id"] == format(ctx.trace_id, "032x")
    assert line["span_id"] == format(ctx.span_id, "016x")
    assert line["service"] == obs.SERVICE_NAME


def test_json_log_has_no_trace_id_outside_a_span():
    assert "trace_id" not in _format("hello")


def test_json_log_masks_emails_and_keeps_structured_fields():
    line = _format("login by admin@scuola.it failed", event="login_failed", attempt=3)
    assert "admin@scuola.it" not in json.dumps(line)
    assert "[email]" in line["message"]
    assert line["event"] == "login_failed" and line["attempt"] == 3


def test_generation_success_is_counted_with_its_outcome(client, school_setup, metrics_recorder):
    total, duration = metrics_recorder
    r = client.post("/api/schedule/generate", json={"week_start": school_setup["week_start"]})
    assert r.json()["status"] == "generated"
    assert total.calls == [(1, {"outcome": "generated"})]
    assert duration.calls and duration.calls[0][1] == {"outcome": "generated"}


def test_unexpected_exception_is_an_internal_error_with_a_trace_correlated_log(
    client, school_setup, metrics_recorder, monkeypatch, caplog,
):
    from app.repositories.schedule import ScheduleRepository

    def boom(self, *args, **kwargs):
        raise KeyError("calendario mancante")

    monkeypatch.setattr(ScheduleRepository, "get_week_context", boom)
    with caplog.at_level(logging.ERROR):
        r = client.post("/api/schedule/generate", json={"week_start": school_setup["week_start"]})

    assert r.json()["status"] == "error"
    total, _ = metrics_recorder
    assert total.calls == [(1, {"outcome": "internal_error"})]
    finished = [rec for rec in caplog.records if getattr(rec, "event", "") == "schedule_generation_finished"]
    assert finished and finished[0].levelno == logging.ERROR
    assert finished[0].outcome == "internal_error"


def test_user_errors_are_not_internal_errors(client, school_setup, metrics_recorder):
    """An approved (locked) week is a user error: it must not trip the on-call alert."""
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})
    client.post(f"/api/schedule/{week}/approve")
    total, _ = metrics_recorder
    total.calls.clear()

    r = client.post("/api/schedule/generate", json={"week_start": week})
    assert r.json()["status"] == "error"
    assert total.calls == [(1, {"outcome": "error"})]
