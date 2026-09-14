"""End-to-end tests for the /api/chat routes."""

import json


def _read_sse_events(response):
    events = []
    for line in response.iter_lines():
        if line.startswith("data:"):
            events.append(json.loads(line[5:].strip()))
    return events


def _generated_slots(client, week):
    """Generate + fetch the persisted schedule: unlike the generate
    response's slots, these carry materia_nome/docente_nome/classe_nome."""
    gen = client.post("/api/schedule/generate", json={"week_start": week}).json()
    assert gen["status"] == "generated", gen
    return gen, client.get(f"/api/schedule/{week}").json()["slots"]


def test_chat_send_streams_sse_events(client, school_setup):
    week = school_setup["week_start"]
    gen = client.post("/api/schedule/generate", json={"week_start": week})
    schedule_id = gen.json().get("schedule_id")

    with client.stream(
        "POST",
        "/api/chat/send",
        json={
            "schedule_id": schedule_id,
            "week_start": week,
            "message": "Sposta matematica di 1A dal martedi al mercoledi",
        },
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
        json={
            "schedule_id": "whatever",
            "week_start": school_setup["week_start"],
            "message": "asdkjaslkdj",
        },
    ) as r:
        assert r.status_code == 200
        events = _read_sse_events(r)

    assert any(e["type"] in ("clarification", "error") for e in events)


def test_chat_send_exclude_day_actually_zeroes_out_that_day(client, school_setup):
    """
    Regression test: chat used to always report a fake "+2 points" success
    without touching the schedule at all. Excluding a docente for one
    giorno must really leave them at 0 hours that day afterward.
    """
    week = school_setup["week_start"]
    gen = client.post("/api/schedule/generate", json={"week_start": week}).json()
    assert gen["status"] == "generated"
    alfa_id = school_setup["teachers_by_name"]["Prof Alfa"]

    with client.stream(
        "POST",
        "/api/chat/send",
        json={
            "schedule_id": gen["schedule_id"],
            "week_start": week,
            "message": "Voglio escludere Prof Alfa martedi",
        },
    ) as r:
        assert r.status_code == 200
        events = _read_sse_events(r)

    ready = next((e for e in events if e["type"] == "ready"), None)
    assert ready is not None, events
    assert ready["new_schedule"]["schedule_id"] == gen["schedule_id"]
    assert not any(
        s["docente_id"] == alfa_id and s["giorno"] == "MARTEDI" for s in ready["new_schedule"]["slots"]
    )


def test_chat_send_move_lesson_rejects_moving_only_one_side_of_a_pair(client, school_setup):
    """
    1A/1B are accoppiate on Matematica in the fixture (same docente, same
    giorno/ora). move_lesson only relocates the named class's own slot(s),
    so asking to move just 1A's must be rejected by the same hard pairing
    constraint modify_slot already enforces - not silently misreported as
    success, the way the old fake "+2 points" heuristic would have.
    """
    week = school_setup["week_start"]
    gen, slots = _generated_slots(client, week)
    matematica_slot = next(s for s in slots if s["materia_nome"] == "Matematica" and s["accoppiata"])
    from_day = matematica_slot["giorno"]
    to_day = "MARTEDI" if from_day != "MARTEDI" else "MERCOLEDI"

    with client.stream(
        "POST",
        "/api/chat/send",
        json={
            "schedule_id": gen["schedule_id"],
            "week_start": week,
            "message": f"Sposta matematica di 1A dal {from_day.lower()} al {to_day.lower()}",
        },
    ) as r:
        assert r.status_code == 200
        events = _read_sse_events(r)

    assert any(e["type"] == "error" for e in events), events


def test_chat_history_is_empty_before_any_message(client, school_setup):
    r = client.get(f"/api/chat/history/{school_setup['week_start']}")
    assert r.status_code == 200
    assert r.json()["messages"] == []


def test_chat_history_returns_lowercase_roles_after_a_message(client, school_setup):
    """Regression test: ChatMessage.ruolo is stored as ADMIN/AI, but the
    frontend's ChatMessage type expects lowercase admin/ai."""
    week = school_setup["week_start"]
    gen = client.post("/api/schedule/generate", json={"week_start": week}).json()

    with client.stream(
        "POST",
        "/api/chat/send",
        json={
            "schedule_id": gen["schedule_id"],
            "week_start": week,
            "message": "Voglio escludere Prof Alfa martedi",
        },
    ) as r:
        list(_read_sse_events(r))

    history = client.get(f"/api/chat/history/{week}").json()
    assert history["messages"], "expected at least the admin message to be saved"
    for m in history["messages"]:
        assert m["role"] in ("admin", "ai")
