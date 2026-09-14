"""End-to-end tests for the /api/setup and /api/calendar routes."""


def test_calendar_upload_accepts_csv(client):
    r = client.post(
        "/api/calendar/upload",
        files={"file": ("calendario.csv", b"data,ore_max_giornata,flag_chiusura\n2026-04-06,6,false\n", "text/csv")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "uploaded"
    assert body["file_type"] == "calendario"


def test_calendar_upload_rejects_non_csv(client):
    r = client.post(
        "/api/calendar/upload",
        files={"file": ("calendario.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 400


def test_setup_validate_success(client, setup_file_data):
    r = client.post("/api/setup/validate", json=setup_file_data)
    assert r.status_code == 200
    body = r.json()
    assert body["can_proceed"] is True
    assert body["overall_status"] == "ready"
    for file_type in ("docenti", "classi", "materie", "assegnazioni", "accoppiamenti", "calendario"):
        assert body["results"][file_type]["success"] is True


def test_setup_validate_reports_errors_for_bad_data(client, setup_file_data):
    setup_file_data["docenti"] = "nome,email,tipo\nProf Alfa,alfa@x.it,STAGISTA\n"
    r = client.post("/api/setup/validate", json=setup_file_data)
    assert r.status_code == 200
    body = r.json()
    assert body["can_proceed"] is False
    assert body["results"]["docenti"]["success"] is False


def test_setup_validate_field_correction(client, setup_file_data):
    client.post("/api/setup/validate", json=setup_file_data)
    r = client.post(
        "/api/setup/validate-field",
        json={"file_type": "docenti", "entity": "Prof Beta", "field": "nome", "new_value": "Prof Beta"},
    )
    assert r.status_code == 200
    assert r.json()["valid"] is True


def test_setup_validate_field_unknown_entity(client, setup_file_data):
    client.post("/api/setup/validate", json=setup_file_data)
    r = client.post(
        "/api/setup/validate-field",
        json={"file_type": "docenti", "entity": "Nessuno", "field": "nome", "new_value": "x"},
    )
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_setup_save_creates_fixed_school_id(client, setup_file_data):
    """
    Regression test: SetupRepository.create_school used to ignore the
    scuola_id it was given and always generate a random UUID, while every
    other route hardcodes scuola_id="sch_1" - so nothing created during
    setup was ever findable afterwards.
    """
    client.post("/api/setup/validate", json=setup_file_data)
    r = client.post(
        "/api/setup/save",
        json={
            "file_ids": [],
            "school_name": "Scuola di Test",
            "school_year": "2025-2026",
            "data_inizio": "2026-01-01",
            "data_fine": "2026-06-30",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "setup_complete"
    assert body["school_id"] == "sch_1"


def test_setup_save_without_prior_validate_returns_error(client):
    r = client.post(
        "/api/setup/save",
        json={"file_ids": [], "school_name": "X", "school_year": "2025-2026"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "error"


def _upload_docenti(client, setup_file_data):
    r = client.post(
        "/api/teachers/upload",
        files={"file": ("docenti.csv", setup_file_data["docenti"].encode(), "text/csv")},
    )
    assert r.status_code == 200, r.text
    return r.json()["file_id"]


def test_apply_correction_updates_cached_teacher(client, setup_file_data):
    """
    Regression test: POST /api/setup/apply-correction ("Salva correzione"
    in the setup wizard) didn't exist as a route at all.
    """
    file_id = _upload_docenti(client, setup_file_data)

    r = client.post(
        "/api/setup/apply-correction",
        json={"file_id": file_id, "correction": {"entity": "Prof Beta", "field": "email", "new_value": "beta@x.it"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "applied"
    assert body["file_type"] == "docenti"


def test_apply_correction_rejects_invalid_value(client, setup_file_data):
    file_id = _upload_docenti(client, setup_file_data)

    r = client.post(
        "/api/setup/apply-correction",
        json={"file_id": file_id, "correction": {"entity": "Prof Beta", "field": "tipo", "new_value": "STAGISTA"}},
    )
    assert r.status_code == 400


def test_apply_correction_unknown_file_id(client, setup_file_data):
    r = client.post(
        "/api/setup/apply-correction",
        json={"file_id": "xyz_does-not-exist", "correction": {"entity": "Prof Beta", "field": "email", "new_value": "x@x.it"}},
    )
    assert r.status_code == 400


def test_add_calendar_date_manual(client, setup_file_data):
    """
    Regression test: POST /api/calendar/add-date-manual (the setup
    wizard's OCR fallback) didn't exist as a route at all.
    """
    r = client.post(
        "/api/calendar/upload",
        files={"file": ("calendario.csv", setup_file_data["calendario"].encode(), "text/csv")},
    )
    assert r.status_code == 200
    file_id = r.json()["file_id"]

    r = client.post(
        "/api/calendar/add-date-manual",
        json={
            "file_id": file_id,
            "date": "2026-04-11",
            "ore_max_giornata": 5,
            "flag_chiusura": False,
            "flag_stage_classe_id": None,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "added"
    assert body["total_dates_loaded"] == 6  # the fixture's 5 rows + this one


def test_add_calendar_date_manual_rejects_bad_ore(client):
    r = client.post(
        "/api/calendar/add-date-manual",
        json={"date": "2026-04-11", "ore_max_giornata": 9, "flag_chiusura": False},
    )
    assert r.status_code == 400


def test_add_calendar_date_manual_rejects_bad_date(client):
    r = client.post(
        "/api/calendar/add-date-manual",
        json={"date": "not-a-date", "ore_max_giornata": 5, "flag_chiusura": False},
    )
    assert r.status_code == 400
