"""End-to-end tests for the /api/chat routes."""

import json


def _read_sse_events(response):
    events = []
    for line in response.iter_lines():
        if line.startswith("data:"):
            events.append(json.loads(line[5:].strip()))
    return events


def test_chat_send_streams_sse_events(client, school_setup):
    week = school_setup["week_start"]
    gen = client.post("/api/schedule/generate", json={"week_start": week})
    schedule_id = gen.json().get("schedule_id")

    with client.stream(
        "POST",
        "/api/chat/send",
        json={"schedule_id": schedule_id, "message": "Sposta matematica di 1A dal martedi al mercoledi"},
    ) as r:
        assert r.status_code == 200
        events = _read_sse_events(r)

    assert events, "expected at least one SSE event"
    assert events[0]["type"] == "thinking"
    assert any(e["type"] in ("suggestion", "clarification", "error") for e in events)


def test_chat_send_unparseable_message_asks_for_clarification_or_errors(client, school_setup):
    with client.stream(
        "POST",
        "/api/chat/send",
        json={"schedule_id": "whatever", "message": "asdkjaslkdj"},
    ) as r:
        assert r.status_code == 200
        events = _read_sse_events(r)

    assert any(e["type"] in ("clarification", "error") for e in events)


def test_chat_history_is_empty_before_any_message(client, school_setup):
    r = client.get("/api/chat/history/some-schedule-id")
    assert r.status_code == 200
    assert r.json()["messages"] == []
