"""End-to-end tests for the /api/schedule routes."""


def _generated_slots(client, week):
    """Generate + fetch the persisted schedule, whose slots carry real DB
    slot_id values (unlike the generate response, which leaves slot_id="")."""
    gen = client.post("/api/schedule/generate", json={"week_start": week}).json()
    assert gen["status"] == "generated", gen
    return client.get(f"/api/schedule/{week}").json()["slots"]


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


def test_generated_schedule_slots_include_names(client, school_setup):
    """
    Regression test: the generate response's slots used to carry only ids
    (classe_id/docente_id/materia_id), unlike every other schedule endpoint
    (get_schedule, modify_slot, apply_quick_action), which already included
    the *_nome fields - the frontend showed raw UUIDs as column headers
    right after clicking "Genera nuovo orario" until the next reload.
    """
    week = school_setup["week_start"]
    body = client.post("/api/schedule/generate", json={"week_start": week}).json()
    assert body["status"] == "generated"
    assert body["slots"], "expected at least one slot"
    for s in body["slots"]:
        assert s["classe_nome"], s
        assert s["docente_nome"], s
        assert s["materia_nome"], s
        assert s["materia_tipo"] in ("TEORIA", "PRATICA")


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


def test_generated_schedule_includes_itemized_conflicts(client, school_setup):
    """
    Regression test: the schedule's `conflicts` list used to not exist at
    all (the frontend's "Conflitti" panel always read an empty/undefined
    list). ScheduleSolver.get_conflicts() now turns the actually-violated
    soft constraints into a human-readable, deduplicated list.
    """
    week = school_setup["week_start"]
    body = client.post("/api/schedule/generate", json={"week_start": week}).json()

    assert body["status"] == "generated"
    assert body["n_soft_conflicts"] > 0, "fixture is expected to trigger real soft-constraint violations"
    assert body["conflicts"], "expected at least one itemized conflict"

    valid_actions = {"force_3_hours_theory", "reduce_contract_hours", "authorize_early_exit", "override_availability"}
    for c in body["conflicts"]:
        assert c["conflict_id"]
        assert isinstance(c["description"], str) and c["description"]
        if c["suggested_action"] is not None:
            assert c["suggested_action"]["action_type"] in valid_actions
            assert c["suggested_action"]["label"]


def test_get_schedule_recomputes_conflicts_on_reload(client, school_setup):
    """Conflicts must be recoverable on a plain GET too (a page refresh),
    not just in the response right after generate/modify/quick-action -
    see ScheduleService._conflicts_for_persisted_schedule."""
    week = school_setup["week_start"]
    generated = client.post("/api/schedule/generate", json={"week_start": week}).json()

    fetched = client.get(f"/api/schedule/{week}").json()
    assert fetched["conflicts"]
    assert {c["conflict_id"] for c in fetched["conflicts"]} == {c["conflict_id"] for c in generated["conflicts"]}


def test_get_schedule_after_generation(client, school_setup):
    """
    Regression test: the response used to nest everything under a
    "schedule" key ({"status": "found", "schedule": {...}}), but the
    frontend fetches this endpoint expecting its `Schedule` type's fields
    (quality_score, slots, ...) at the top level.
    """
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})

    r = client.get(f"/api/schedule/{week}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "found"
    assert "quality_score" in body
    assert "slots" in body


def test_get_schedule_for_week_without_data(client, school_setup):
    r = client.get("/api/schedule/2099-01-05")
    assert r.status_code == 404


def test_regenerate_schedule_replaces_slots_in_place(client, school_setup):
    """
    Regression test: the frontend's "Genera da zero" button posts to
    /schedule/{week}/regenerate, which didn't exist as a route before.
    Regenerating an existing week must keep the same schedule_id rather
    than creating a second OrarioSettimanale row for that week.
    """
    week = school_setup["week_start"]
    first = client.post("/api/schedule/generate", json={"week_start": week}).json()
    assert first["status"] == "generated"
    schedule_id = first["schedule_id"]

    r = client.post(f"/api/schedule/{week}/regenerate")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "generated"
    assert body["schedule_id"] == schedule_id

    fetched = client.get(f"/api/schedule/{week}").json()
    assert fetched["schedule_id"] == schedule_id


def test_regenerate_locked_after_approval(client, school_setup):
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})
    client.post(f"/api/schedule/{week}/approve")

    r = client.post(f"/api/schedule/{week}/regenerate")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"


def test_quality_score_endpoint(client, school_setup):
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})

    r = client.get(f"/api/schedule/{week}/quality-score")
    assert r.status_code == 200
    body = r.json()
    assert "quality_score" in body
    assert "quality_level" in body
    assert "n_soft_conflicts" in body["details"]


def test_quality_score_endpoint_without_schedule(client, school_setup):
    r = client.get("/api/schedule/2099-01-05/quality-score")
    assert r.status_code == 404


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
    body = r.json()
    assert body["status"] == "generated"
    assert body["pdf_url"] == f"/api/schedule/{week}/export-pdf/file"


def test_export_pdf_without_schedule(client, school_setup):
    r = client.get("/api/schedule/2099-01-05/export-pdf")
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_export_pdf_file_is_a_real_pdf(client, school_setup):
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})

    r = client.get(f"/api/schedule/{week}/export-pdf/file")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_export_pdf_file_without_schedule_is_404(client, school_setup):
    r = client.get("/api/schedule/2099-01-05/export-pdf/file")
    assert r.status_code == 404


def test_modify_slot_endpoint_smoke(client, school_setup):
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})

    r = client.post(
        f"/api/schedule/{week}/modify-slot",
        json={"slot_id": "whatever", "changes": {"giorno": "martedi"}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_modify_slot_identity_change_recalculates_score(client, school_setup):
    """Re-submitting a slot's own giorno/ora is a no-op move: it must still
    go through the real solve+recalculate path and come back as 'modified'
    with the full updated schedule (not the old hardcoded placeholder)."""
    week = school_setup["week_start"]
    slot = _generated_slots(client, week)[0]

    r = client.post(
        f"/api/schedule/{week}/modify-slot",
        json={
            "slot_id": slot["slot_id"],
            "changes": {"giorno": slot["giorno"], "ora_inizio": slot["ora_inizio"]},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "modified"
    assert "quality_score" in body
    assert any(s["slot_id"] == slot["slot_id"] for s in body["slots"])


def test_modify_slot_rejects_moving_only_one_side_of_a_pair(client, school_setup):
    """1A/1B Matematica are accoppiate (paired) in the fixture, taught by the
    same docente at the same giorno/ora. Moving only one side must fail the
    hard pairing constraint instead of silently "succeeding" like the old
    placeholder did."""
    week = school_setup["week_start"]
    paired_slot = next(s for s in _generated_slots(client, week) if s["accoppiata"])

    other_giorno = "MARTEDI" if paired_slot["giorno"] != "MARTEDI" else "MERCOLEDI"
    r = client.post(
        f"/api/schedule/{week}/modify-slot",
        json={"slot_id": paired_slot["slot_id"], "changes": {"giorno": other_giorno}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_modify_slot_rejects_unassigned_teacher(client, school_setup):
    week = school_setup["week_start"]
    slot = _generated_slots(client, week)[0]

    r = client.post(
        f"/api/schedule/{week}/modify-slot",
        json={"slot_id": slot["slot_id"], "changes": {"docente_id": "does-not-exist"}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_modify_slot_on_approved_schedule_is_locked(client, school_setup):
    week = school_setup["week_start"]
    slot = _generated_slots(client, week)[0]
    client.post(f"/api/schedule/{week}/approve")

    r = client.post(
        f"/api/schedule/{week}/modify-slot",
        json={"slot_id": slot["slot_id"], "changes": {"giorno": slot["giorno"]}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"
    assert "locked" in body["message"].lower()


def test_apply_quick_action_endpoint_smoke(client, school_setup):
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})

    r = client.post(
        f"/api/schedule/{week}/apply-quick-action",
        json={"action_type": "force_3_hours_theory", "parameters": {}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "applied"
    assert "quality_score" in body


def test_apply_quick_action_rejects_unknown_action(client, school_setup):
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})

    r = client.post(
        f"/api/schedule/{week}/apply-quick-action",
        json={"action_type": "not_a_real_action", "parameters": {}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_apply_quick_action_without_schedule(client, school_setup):
    r = client.post(
        "/api/schedule/2099-01-05/apply-quick-action",
        json={"action_type": "force_3_hours_theory", "parameters": {}},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def test_apply_quick_action_on_approved_schedule_is_locked(client, school_setup):
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})
    client.post(f"/api/schedule/{week}/approve")

    r = client.post(
        f"/api/schedule/{week}/apply-quick-action",
        json={"action_type": "force_3_hours_theory", "parameters": {}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error"
    assert "locked" in body["message"].lower()


def test_quick_action_override_availability_unlocks_contract_teacher(client, school_setup):
    """Prof Beta is CONTRATTO with no recorded availability for the week, so
    the hard availability constraint zeroes out every one of his slots on a
    plain generation. The 'Deroga disponibilità' quick action, scoped to
    him, should lift that and let the solver actually use him."""
    week = school_setup["week_start"]
    gen = client.post("/api/schedule/generate", json={"week_start": week}).json()
    assert gen["status"] == "generated"
    beta_id = school_setup["teachers_by_name"]["Prof Beta"]
    assert not any(s["docente_id"] == beta_id for s in gen["slots"])

    r = client.post(
        f"/api/schedule/{week}/apply-quick-action",
        json={"action_type": "override_availability", "teacher_id": beta_id, "parameters": {}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "applied"
    assert any(s["docente_id"] == beta_id for s in body["slots"])
