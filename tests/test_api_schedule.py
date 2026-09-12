"""End-to-end tests for the /api/schedule routes."""


def test_generate_schedule_accepts_json_body(client, school_setup):
    """
    Regression test: POST /api/schedule/generate used to declare week_start
    as a plain scalar parameter, which FastAPI binds from the query string,
    not the JSON body the frontend actually sends.
    """
    r = client.post(
        "/api/schedule/generate",
        json={"week_start": school_setup["week_start"], "include_preferences": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("generated", "infeasible", "timeout")


def test_generated_schedule_respects_closure_day(client, school_setup):
    """The fixture's calendar flags 2026-04-06 (Monday) as a closure day."""
    week = school_setup["week_start"]
    r = client.post("/api/schedule/generate", json={"week_start": week})
    body = r.json()
    assert body["status"] == "generated"
    assert not any(s["giorno"] == "LUNEDI" for s in body["slots"])


def test_generated_schedule_pairs_shared_teacher(client, school_setup):
    """
    Regression test: paired classes taught by the same docente
    (1A/1B on Matematica, both by Prof Alfa in the fixture) used to always
    get 0 hours because of a hard-constraint contradiction. Any accoppiata
    slot must have a matching slot for the other class, same time, same
    docente.
    """
    week = school_setup["week_start"]
    r = client.post("/api/schedule/generate", json={"week_start": week})
    slots = r.json()["slots"]
    paired = [s for s in slots if s["accoppiata"]]

    by_time = {}
    for s in paired:
        by_time.setdefault((s["giorno"], s["ora_inizio"]), []).append(s)

    for key, group in by_time.items():
        assert len(group) == 2, f"expected 2 classes paired at {key}, got {group}"
        assert len({s["docente_id"] for s in group}) == 1


def test_get_schedule_after_generation(client, school_setup):
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})

    r = client.get(f"/api/schedule/{week}")
    assert r.status_code == 200
    assert r.json()["status"] == "found"


def test_get_schedule_for_week_without_data(client, school_setup):
    r = client.get("/api/schedule/2099-01-05")
    assert r.status_code == 200
    assert r.json()["status"] == "not_found"


def test_quality_score_endpoint(client, school_setup):
    r = client.get(f"/api/schedule/{school_setup['week_start']}/quality-score")
    assert r.status_code == 200
    assert "quality_score" in r.json()


def test_approve_schedule(client, school_setup):
    """
    Regression test: approve_schedule used to query the nonexistent column
    OrarioSettimanale.data_inizio (the real column is settimana_inizio),
    crashing every approval attempt.
    """
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})

    r = client.post(f"/api/schedule/{week}/approve")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["stato"] == "APPROVATO"


def test_approve_schedule_without_generation_first(client, school_setup):
    r = client.post(f"/api/schedule/2099-01-05/approve")
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_export_pdf_endpoint(client, school_setup):
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})

    r = client.get(f"/api/schedule/{week}/export-pdf")
    assert r.status_code == 200
    assert r.json()["status"] == "generated"


def test_modify_slot_endpoint_smoke(client, school_setup):
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})

    r = client.post(
        f"/api/schedule/{week}/modify-slot",
        json={"slot_id": "whatever", "changes": {"giorno": "martedi"}},
    )
    assert r.status_code == 200


def test_apply_quick_action_endpoint_smoke(client, school_setup):
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})

    r = client.post(
        f"/api/schedule/{week}/apply-quick-action",
        json={"action_type": "force_3_hours_theory", "parameters": {}},
    )
    assert r.status_code == 200
