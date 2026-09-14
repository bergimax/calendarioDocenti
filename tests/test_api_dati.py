"""End-to-end tests for the "Dati scuola" CRUD routes (classes, subjects,
assignments, class-pairings, calendar) plus teacher create/update/delete,
which the /dati/*.tsx pages (via CrudTable) rely on."""


def test_classes_crud(client, school_setup):
    r = client.post("/api/classes", json={"nome": "5Z", "n_studenti": "24"})
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["nome"] == "5Z"
    assert created["n_studenti"] == 24
    classe_id = created["classe_id"]

    r = client.get("/api/classes")
    assert r.status_code == 200
    assert any(c["classe_id"] == classe_id for c in r.json())

    r = client.put(f"/api/classes/{classe_id}", json={"nome": "5Z", "n_studenti": "26"})
    assert r.status_code == 200
    assert r.json()["n_studenti"] == 26

    r = client.delete(f"/api/classes/{classe_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "deleted"
    assert not any(c["classe_id"] == classe_id for c in client.get("/api/classes").json())


def test_create_class_requires_nome(client, school_setup):
    r = client.post("/api/classes", json={"n_studenti": "20"})
    assert r.status_code == 400


def test_update_unknown_class_is_404(client, school_setup):
    r = client.put("/api/classes/does-not-exist", json={"nome": "X"})
    assert r.status_code == 404


def test_subjects_crud(client, school_setup):
    r = client.post("/api/subjects", json={"nome": "Disegno", "tipo": "PRATICA", "peso_cognitivo": "ALTO"})
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["tipo"] == "PRATICA"
    materia_id = created["materia_id"]

    r = client.put(f"/api/subjects/{materia_id}", json={"tipo": "TEORIA"})
    assert r.status_code == 200
    assert r.json()["tipo"] == "TEORIA"

    r = client.delete(f"/api/subjects/{materia_id}")
    assert r.status_code == 200


def test_create_subject_rejects_invalid_tipo(client, school_setup):
    r = client.post("/api/subjects", json={"nome": "X", "tipo": "BOH"})
    assert r.status_code == 400


def test_assignments_crud_includes_monte_ore(client, school_setup):
    docente_id = next(iter(school_setup["teachers_by_name"].values()))
    classe = client.post("/api/classes", json={"nome": "1Z"}).json()
    materia = client.post("/api/subjects", json={"nome": "Chimica", "tipo": "TEORIA"}).json()

    r = client.post("/api/assignments", json={
        "docente_id": docente_id,
        "classe_id": classe["classe_id"],
        "materia_id": materia["materia_id"],
        "ore_totali": "60",
    })
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["ore_totali"] == 60
    assert created["ore_erogate"] == 0
    assignment_id = created["assignment_id"]

    r = client.put(f"/api/assignments/{assignment_id}", json={"ore_totali": "90", "ore_erogate": "10"})
    assert r.status_code == 200
    body = r.json()
    assert body["ore_totali"] == 90
    assert body["ore_erogate"] == 10

    r = client.delete(f"/api/assignments/{assignment_id}")
    assert r.status_code == 200
    assert not any(a["assignment_id"] == assignment_id for a in client.get("/api/assignments").json())


def test_class_pairings_crud(client, school_setup):
    a = client.post("/api/classes", json={"nome": "2Y"}).json()
    b = client.post("/api/classes", json={"nome": "2Z"}).json()
    materia = client.post("/api/subjects", json={"nome": "Ginnastica", "tipo": "PRATICA"}).json()

    r = client.post("/api/class-pairings", json={
        "classe_a_id": a["classe_id"], "classe_b_id": b["classe_id"], "materia_id": materia["materia_id"],
    })
    assert r.status_code == 200, r.text
    pairing_id = r.json()["pairing_id"]

    r = client.get("/api/class-pairings")
    assert any(p["pairing_id"] == pairing_id for p in r.json())

    r = client.delete(f"/api/class-pairings/{pairing_id}")
    assert r.status_code == 200


def test_calendar_crud_coerces_form_strings(client, school_setup):
    """The frontend's CrudTable always posts string values, even for the
    boolean/int fields (native <select> option values)."""
    r = client.post("/api/calendar", json={
        "data": "2026-12-24", "ore_max_giornata": "4", "flag_chiusura": "true",
    })
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["ore_max_giornata"] == 4
    assert created["flag_chiusura"] is True
    date_id = created["date_id"]

    r = client.put(f"/api/calendar/{date_id}", json={"flag_chiusura": "false"})
    assert r.status_code == 200
    assert r.json()["flag_chiusura"] is False

    r = client.delete(f"/api/calendar/{date_id}")
    assert r.status_code == 200


def test_calendar_rejects_bad_date(client, school_setup):
    r = client.post("/api/calendar", json={"data": "not-a-date", "ore_max_giornata": "5"})
    assert r.status_code == 400


def test_create_and_update_teacher(client, school_setup):
    r = client.post("/api/teachers", json={"nome": "Prof Nuovo", "tipo": "CONTRATTO"})
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["tipo"] == "CONTRATTO"
    teacher_id = created["teacher_id"]

    r = client.put(f"/api/teachers/{teacher_id}", json={"email": "nuovo@x.it"})
    assert r.status_code == 200
    assert r.json()["email"] == "nuovo@x.it"

    r = client.delete(f"/api/teachers/{teacher_id}")
    assert r.status_code == 200
    assert not any(t["teacher_id"] == teacher_id for t in client.get("/api/teachers").json())


def test_create_teacher_rejects_invalid_tipo(client, school_setup):
    r = client.post("/api/teachers", json={"nome": "X", "tipo": "STAGISTA"})
    assert r.status_code == 400


def test_delete_teacher_with_assignments_is_a_clean_error(client, school_setup):
    """Regression-style test: deleting a docente with related Assegnazione/
    MonteOreAnnuale rows must not 500 on a raw FK IntegrityError."""
    docente_id = school_setup["teachers_by_name"]["Prof Alfa"]
    r = client.delete(f"/api/teachers/{docente_id}")
    assert r.status_code == 400
