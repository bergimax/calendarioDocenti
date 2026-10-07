"""End-to-end tests for the /api/schedule routes."""

from app.domain.soft_weights import DEFAULT_SOFT_WEIGHTS


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


def test_feedback_requires_existing_schedule(client, school_setup):
    week = school_setup["week_start"]
    assert client.get(f"/api/schedule/{week}/feedback").status_code == 404
    r = client.post(f"/api/schedule/{week}/feedback", json={"voto": 3})
    assert r.status_code == 404


def test_feedback_is_stored_with_score_snapshot_and_history(client, school_setup):
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})

    empty = client.get(f"/api/schedule/{week}/feedback").json()
    assert empty["current"] is None and empty["history"] == []
    codes = {m["code"] for m in empty["motivi_disponibili"]}
    assert {"contractor_gap", "single_classe_day", "altro"} <= codes

    r = client.post(
        f"/api/schedule/{week}/feedback",
        json={"voto": 2, "motivi": ["contractor_gap", "contractor_gap", "altro"], "nota": "  troppi buchi  "},
    )
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["voto"] == 2
    assert saved["motivi"] == ["contractor_gap", "altro"]  # deduped
    assert saved["nota"] == "troppi buchi"
    assert saved["quality_score"] is not None and saved["stato"] == "BOZZA"

    client.post(f"/api/schedule/{week}/feedback", json={"voto": 4})
    got = client.get(f"/api/schedule/{week}/feedback").json()
    assert len(got["history"]) == 2  # append-only, earlier rating kept
    assert got["current"]["voto"] == 4


def test_feedback_validation(client, school_setup):
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})
    for voto in (0, 6):
        assert client.post(f"/api/schedule/{week}/feedback", json={"voto": voto}).status_code == 422
    r = client.post(f"/api/schedule/{week}/feedback", json={"voto": 3, "motivi": ["inventato"]})
    assert r.status_code == 422


# --- learning from ratings: soft-weight proposals (app/services/soft_weights.py) ---

def _rate(client, week, voto, motivi):
    r = client.post(f"/api/schedule/{week}/feedback", json={"voto": voto, "motivi": motivi})
    assert r.status_code == 200, r.text


def _weight(state, kind):
    return next(w["current"] for w in state["weights"] if w["kind"] == kind)


def test_soft_weights_default_state_has_no_proposals(client, school_setup):
    state = client.get("/api/soft-weights").json()
    assert state["proposals"] == [] and state["history"] == []
    assert _weight(state, "teoria_consecutive") == 10
    assert all(w["current"] == w["default"] for w in state["weights"])


def test_proposal_needs_two_low_ratings_on_a_tunable_reason(client, school_setup):
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})

    _rate(client, week, 2, ["teoria_consecutive"])
    assert client.get("/api/soft-weights").json()["proposals"] == []  # only one

    _rate(client, week, 5, ["teoria_consecutive"])  # a good rating is not a complaint
    _rate(client, week, 2, ["friday_late_start"])  # not tunable by weight
    _rate(client, week, 2, ["friday_late_start"])
    assert client.get("/api/soft-weights").json()["proposals"] == []

    _rate(client, week, 1, ["teoria_consecutive"])
    props = client.get("/api/soft-weights").json()["proposals"]
    assert [p["kind"] for p in props] == ["teoria_consecutive"]
    p = props[0]
    assert p["current"] == 10 and p["n_feedback"] == 2
    # severity 2 + 3 = 5 points -> +50% (the cap on a single step)
    assert p["proposed"] == 15


def test_applying_a_proposal_changes_the_weight_once_and_can_be_reset(client, school_setup):
    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})
    _rate(client, week, 2, ["contractor_gap"])
    _rate(client, week, 2, ["contractor_gap"])

    state = client.post("/api/soft-weights/apply", json={}).json()
    assert _weight(state, "contractor_gap") > DEFAULT_SOFT_WEIGHTS["contractor_gap"]
    assert state["proposals"] == []  # the same ratings are not counted again
    assert state["history"][0]["kind"] == "contractor_gap"

    # nothing left to apply
    again = client.post("/api/soft-weights/apply", json={}).json()
    assert _weight(again, "contractor_gap") == _weight(state, "contractor_gap")

    reset = client.post("/api/soft-weights/reset", json={"kind": "contractor_gap"}).json()
    assert _weight(reset, "contractor_gap") == DEFAULT_SOFT_WEIGHTS["contractor_gap"]
    assert reset["proposals"] == []  # ratings before the reset are not reused
    assert len(reset["history"]) == 2 and reset["history"][0]["reset"] is True


def test_apply_and_reset_reject_unknown_kinds(client, school_setup):
    assert client.post("/api/soft-weights/apply", json={"kinds": ["classe_unfilled"]}).status_code == 422
    assert client.post("/api/soft-weights/reset", json={"kind": "classe_unfilled"}).status_code == 422


def test_generation_uses_the_applied_weights(client, school_setup, monkeypatch):
    import app.domain.solver as solver_module

    seen = []
    real = solver_module.ScheduleSolver

    class Spy(real):
        def __init__(self, *a, **kw):
            seen.append(kw.get("soft_weights"))
            super().__init__(*a, **kw)

    week = school_setup["week_start"]
    client.post("/api/schedule/generate", json={"week_start": week})
    _rate(client, week, 1, ["single_classe_day"])
    _rate(client, week, 1, ["single_classe_day"])
    applied = client.post("/api/soft-weights/apply", json={}).json()
    new_weight = _weight(applied, "single_classe_day")
    assert new_weight > 10

    monkeypatch.setattr(solver_module, "ScheduleSolver", Spy)
    client.post(f"/api/schedule/{week}/regenerate", json={"week_start": week})
    assert seen and all(w["single_classe_day"] == new_weight for w in seen)


def _erogate_by_assignment(client):
    return {a["assignment_id"]: a["ore_erogate"] for a in client.get("/api/assignments").json()}


def test_approving_a_week_scales_the_hours_of_its_lessons_once(client, school_setup):
    week = school_setup["week_start"]
    slots = _generated_slots(client, week)
    assert slots
    before = _erogate_by_assignment(client)
    assert set(before.values()) == {0}

    r = client.post(f"/api/schedule/{week}/approve")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    # every lesson of the week is one delivered hour on its assegnazione
    assert body["ore_scalate"] == len(slots)
    after = _erogate_by_assignment(client)
    assert sum(after.values()) == len(slots)

    # approving again must not scale the same hours a second time
    again = client.post(f"/api/schedule/{week}/approve").json()
    assert again["status"] == "approved" and again["ore_scalate"] == 0
    assert _erogate_by_assignment(client) == after


def test_next_weeks_residual_hours_drop_after_approval(client, school_setup):
    from datetime import date

    from app.database import SessionLocal
    from app.repositories.schedule import ScheduleRepository

    week = school_setup["week_start"]
    _generated_slots(client, week)

    def residue_total():
        db = SessionLocal()
        try:
            ctx = ScheduleRepository(db).get_week_context("sch_1", date.fromisoformat(week))
            return sum(a.ore_residue for a in ctx.assegnazioni)
        finally:
            db.close()

    total_before = residue_total()
    n_slots = len(client.get(f"/api/schedule/{week}").json()["slots"])
    client.post(f"/api/schedule/{week}/approve")
    assert residue_total() == total_before - n_slots


def test_assign_slot_asks_confirmation_before_forcing_a_rule(client, school_setup, monkeypatch):
    """Una forzatura che rompe una regola non si salva da sola: l'API dice quale regola e
    aspetta la conferma dell'admin; con confirm=True esegue."""
    from app.domain.solver import ScheduleSolver

    week = school_setup["week_start"]
    slots = _generated_slots(client, week)
    target = next(s for s in slots if not s["accoppiata"])
    n_before = len(slots)

    # libero l'ora della lezione e provo a rimetterla (stesso docente e tipo)
    r = client.post(f"/api/schedule/{week}/conflicts/reject", json={
        "classe_id": target["classe_id"], "giorno": target["giorno"], "ora_inizio": target["ora_inizio"],
    })
    assert r.status_code == 200 and len(r.json()["slots"]) == n_before - 1

    original = ScheduleSolver.get_conflicts
    calls = {"n": 0}

    def with_forced_rule(self):
        # solo la prima valutazione (quella con la nuova lezione) ha la regola di prova:
        # la seconda è lo stato "prima" dell'orario, che non ce l'ha
        calls["n"] += 1
        return original(self) + ([] if calls["n"] > 1 else [{
            "conflict_id": "x", "chiave": "paired_hours_override|x|y|LUNEDI", "kind": "paired_hours_override",
            "description": "Regola di prova forzata", "avviso": False,
            "classe_id": target["classe_id"], "docente_id": target["docente_id"], "giorno": "LUNEDI",
        }])

    monkeypatch.setattr(ScheduleSolver, "get_conflicts", with_forced_rule)
    body = {
        "classe_id": target["classe_id"], "giorno": target["giorno"], "ora_inizio": target["ora_inizio"],
        "docente_id": target["docente_id"], "materia_id": target["materia_id"],
    }

    asked = client.post(f"/api/schedule/{week}/assign-slot", json=body).json()
    assert asked["status"] == "needs_confirmation", asked
    assert [r["description"] for r in asked["regole"]] == ["Regola di prova forzata"]
    # non è stato salvato nulla
    assert len(client.get(f"/api/schedule/{week}").json()["slots"]) == n_before - 1

    done = client.post(f"/api/schedule/{week}/assign-slot", json={**body, "confirm": True}).json()
    assert done.get("status") != "needs_confirmation" and done.get("status") != "error", done
    assert len(client.get(f"/api/schedule/{week}").json()["slots"]) == n_before


def test_assign_slot_always_reports_forced_rules_even_when_none(client, school_setup):
    """L'esito dell'assegnazione manuale dice sempre le regole forzate, anche "nessuna"."""
    week = school_setup["week_start"]
    slots = _generated_slots(client, week)
    target = next(s for s in slots if not s["accoppiata"])
    client.post(f"/api/schedule/{week}/conflicts/reject", json={
        "classe_id": target["classe_id"], "giorno": target["giorno"], "ora_inizio": target["ora_inizio"],
    })
    done = client.post(f"/api/schedule/{week}/assign-slot", json={
        "classe_id": target["classe_id"], "giorno": target["giorno"], "ora_inizio": target["ora_inizio"],
        "docente_id": target["docente_id"], "materia_id": target["materia_id"], "confirm": True,
    }).json()
    assert done.get("status") != "error", done
    assert done["message"].startswith("Assegnata"), done["message"]
    assert ("Nessuna regola forzata" in done["message"]) == (done["regole_forzate"] == [])
    assert isinstance(done["regole_forzate"], list)

    # le opzioni dicono con quali classi è la coppia
    opts = client.get(f"/api/schedule/{week}/assignable/{target['classe_id']}").json()["options"]
    assert all("partner_classi" in o for o in opts)


def test_manual_assignment_can_force_any_rule_and_reports_it(client, school_setup):
    """Anche in un giorno di chiusura (prima rifiutato): si può forzare, dicendo la regola rotta."""
    week = school_setup["week_start"]  # il lunedì della fixture è chiuso
    slots = _generated_slots(client, week)
    base = next(s for s in slots if not s["accoppiata"])
    n_before = len(slots)
    body = {
        "classe_id": base["classe_id"], "giorno": "LUNEDI", "ora_inizio": 8,
        "docente_id": base["docente_id"], "materia_id": base["materia_id"],
    }

    asked = client.post(f"/api/schedule/{week}/assign-slot", json=body).json()
    assert asked["status"] == "needs_confirmation", asked
    assert asked["regole"], "deve dire quale regola forza"

    done = client.post(f"/api/schedule/{week}/assign-slot", json={**body, "confirm": True}).json()
    assert done.get("status") != "error", done
    assert "Regole forzate" in done["message"] and done["regole_forzate"]
    assert len(client.get(f"/api/schedule/{week}").json()["slots"]) == n_before + 1


def test_clicking_a_lesson_can_replace_the_docente(client, school_setup):
    """Su una lezione già assegnata: sostituire il docente con un'altra scelta della classe."""
    week = school_setup["week_start"]
    slots = _generated_slots(client, week)
    n_before = len(slots)
    target = other = None
    for s in (x for x in slots if not x["accoppiata"]):
        opts = client.get(f"/api/schedule/{week}/assignable/{s['classe_id']}").json()["options"]
        alt = next((o for o in opts if o["docente_id"] != s["docente_id"]), None)
        if alt:
            target, other = s, alt
            break
    assert other, "la fixture ha una classe con più docenti"
    body = {
        "classe_id": target["classe_id"], "giorno": target["giorno"], "ora_inizio": target["ora_inizio"],
        "docente_id": other["docente_id"], "materia_id": other["materia_id"], "confirm": True,
    }

    # senza "replace" l'ora occupata non si tocca
    refused = client.post(f"/api/schedule/{week}/assign-slot", json=body).json()
    assert refused["status"] == "error" and "sostituiscila" in refused["message"]

    done = client.post(f"/api/schedule/{week}/assign-slot", json={**body, "replace": True}).json()
    assert done.get("status") != "error", done
    now = client.get(f"/api/schedule/{week}").json()["slots"]
    here = [s for s in now if s["classe_id"] == target["classe_id"] and s["giorno"] == target["giorno"]
            and s["ora_inizio"] == target["ora_inizio"]]
    assert [s["docente_id"] for s in here] == [other["docente_id"]]
    assert len(now) >= n_before - 1
