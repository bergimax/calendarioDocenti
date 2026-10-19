"""The alert -> on-call agent relay: payload shape, firing/resolved handling, de-duplication."""

import json

import pytest

from oncall import relay

ALERT = {
    "status": "firing",
    "labels": {"alertname": "Timetable generation failing", "severity": "critical",
               "service": "calendario-backend", "journey": "schedule-generation"},
    "annotations": {"summary": "Admins cannot generate the weekly timetable"},
    "startsAt": "2026-10-19T14:15:20Z",
}
LOGS = [{"ts": "1", "line": "boom", "trace_id": "abc123", "stacktrace": "KeyError: 'ora_inizio'"}]


@pytest.fixture(autouse=True)
def reset_relay(monkeypatch):
    relay._last_sent.clear()
    sent = []
    monkeypatch.setattr(relay, "fetch_error_logs", lambda *a, **k: LOGS)
    monkeypatch.setattr(relay, "send_dispatch", lambda body: sent.append(body) or "dispatched")
    return sent


def test_build_dispatch_is_a_repository_dispatch_with_logs_and_trace_ids():
    body = relay.build_dispatch(ALERT, LOGS)
    assert body["event_type"] == "alert"
    p = body["client_payload"]
    assert p["alertname"] == "Timetable generation failing"
    assert p["trace_ids"] == ["abc123"]
    assert json.loads(p["recent_error_logs"])[0]["stacktrace"].startswith("KeyError")
    assert len(p) <= 10, "repository_dispatch allows at most 10 client_payload properties"


def test_firing_alert_wakes_the_agent_once(reset_relay):
    results = relay.handle_alerts({"alerts": [ALERT]}, now=1000)
    assert results == ["Timetable generation failing: dispatched"]
    assert len(reset_relay) == 1

    again = relay.handle_alerts({"alerts": [ALERT]}, now=1000 + 60)
    assert "skipped" in again[0]
    assert len(reset_relay) == 1, "a repeat inside the dedup window must not start a second agent"

    later = relay.handle_alerts({"alerts": [ALERT]}, now=1000 + relay.DEDUP_SECONDS + 1)
    assert later == ["Timetable generation failing: dispatched"]


def test_resolved_alerts_do_not_wake_the_agent(reset_relay):
    assert relay.handle_alerts({"alerts": [{**ALERT, "status": "resolved"}]}) == []
    assert reset_relay == []
