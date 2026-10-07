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


def _rows(client, classi):
    return [x for x in client.get("/api/assignments").json() if x["classe_id"] in classi]


def test_assignment_from_pairing_creates_both_classes(client, school_setup):
    docente_id = next(iter(school_setup["teachers_by_name"].values()))
    a = client.post("/api/classes", json={"nome": "3Y"}).json()
    b = client.post("/api/classes", json={"nome": "3Z"}).json()
    pairing_id = client.post("/api/class-pairings", json={
        "classe_a_id": a["classe_id"], "classe_b_id": b["classe_id"],
    }).json()["pairing_id"]
    classi = {a["classe_id"], b["classe_id"]}

    r = client.post("/api/assignments", json={
        "docente_id": docente_id, "accoppiamento_id": pairing_id, "ore_totali": "40",
    })
    assert r.status_code == 200, r.text
    rows = _rows(client, classi)
    assert {x["classe_id"] for x in rows} == classi
    assert all(x["ore_totali"] == 40 and not x["singola"] for x in rows)

    # Ogni riga conosce l'altra metà della coppia
    by_classe = {x["classe_id"]: x for x in rows}
    assert by_classe[a["classe_id"]]["partner_assignment_ids"] == [by_classe[b["classe_id"]]["assignment_id"]]

    # Aggiornare le ore su una riga le aggiorna anche sull'altra
    client.put(f"/api/assignments/{rows[0]['assignment_id']}", json={"ore_totali": "55"})
    assert all(x["ore_totali"] == 55 for x in _rows(client, classi))

    # Riassegnare la stessa coppia non crea duplicati
    r = client.post("/api/assignments", json={"docente_id": docente_id, "accoppiamento_id": pairing_id})
    assert r.status_code == 400

    # Eliminare una riga elimina entrambe le classi
    client.delete(f"/api/assignments/{rows[0]['assignment_id']}")
    assert not _rows(client, classi)


def test_coppia_and_singola_of_the_same_class_are_separate_entities(client, school_setup):
    """Stesso docente e stessa classe: la coppia e la singola sono due assegnazioni, con monte ore
    propri (non condivisi); ridurre uno non tocca l'altro."""
    docente_id = next(iter(school_setup["teachers_by_name"].values()))
    a = client.post("/api/classes", json={"nome": "4Y"}).json()
    b = client.post("/api/classes", json={"nome": "4Z"}).json()
    c = client.post("/api/classes", json={"nome": "1X"}).json()
    pairing_id = client.post("/api/class-pairings", json={
        "classe_a_id": a["classe_id"], "classe_b_id": b["classe_id"],
    }).json()["pairing_id"]
    classi = {a["classe_id"], b["classe_id"], c["classe_id"]}

    client.post("/api/assignments", json={"docente_id": docente_id, "accoppiamento_id": pairing_id, "ore_totali": "40"})
    r = client.post("/api/assignments", json={"docente_id": docente_id, "classe_id": a["classe_id"], "ore_totali": "25"})
    assert r.status_code == 200, r.text
    assert r.json()["singola"] is True and r.json()["partner_classe_ids"] == []
    client.post("/api/assignments", json={"docente_id": docente_id, "classe_id": c["classe_id"], "ore_totali": "10"})

    rows = _rows(client, classi)
    coppia = [x for x in rows if x["partner_classe_ids"]]
    assert {x["classe_id"] for x in coppia} == {a["classe_id"], b["classe_id"]}  # la coppia resta tale
    assert all(x["ore_totali"] == 40 for x in coppia)  # 40 per la coppia...
    singola_a = next(x for x in rows if x["singola"] and x["classe_id"] == a["classe_id"])
    assert singola_a["ore_totali"] == 25  # ...25 per la singola della stessa classe
    assert len([x for x in rows if x["singola"]]) == 2

    # stesso docente + stessa classe + stesso tipo non si duplica
    r = client.post("/api/assignments", json={"docente_id": docente_id, "classe_id": a["classe_id"]})
    assert r.status_code == 400

    # cambiare le ore della singola non tocca la coppia, e viceversa
    client.put(f"/api/assignments/{singola_a['assignment_id']}", json={"ore_totali": "5", "ore_erogate": "1"})
    rows = _rows(client, classi)
    assert all(x["ore_totali"] == 40 for x in rows if x["partner_classe_ids"])
    assert next(x for x in rows if x["singola"] and x["classe_id"] == a["classe_id"])["ore_totali"] == 5

    # eliminare la singola non tocca la coppia né il suo monte ore
    client.delete(f"/api/assignments/{singola_a['assignment_id']}")
    rows = _rows(client, classi)
    assert len([x for x in rows if x["partner_classe_ids"]]) == 2
    assert all(x["ore_totali"] == 40 for x in rows if x["partner_classe_ids"])


def test_group_of_four_classes_is_created_and_assigned_in_one_go(client, school_setup):
    docente_id = next(iter(school_setup["teachers_by_name"].values()))
    classi = [client.post("/api/classes", json={"nome": f"4{x}"}).json()["classe_id"] for x in "ABCD"]

    # un solo invio crea tutte le 6 coppie tra le 4 classi
    r = client.post("/api/class-pairings", json={"classi_ids": ",".join(classi), "docente_id": docente_id})
    assert r.status_code == 200, r.text
    mine = [p for p in client.get("/api/class-pairings").json() if p["classe_a_id"] in classi]
    assert len(mine) == 6
    # rifarlo non duplica nulla
    assert client.post("/api/class-pairings", json={
        "classi_ids": ",".join(classi), "docente_id": docente_id,
    }).status_code == 400

    # un'unica assegnazione dal gruppo crea tutte e 4 le classi
    r = client.post("/api/assignments", json={
        "docente_id": docente_id, "accoppiamento_id": mine[0]["pairing_id"], "ore_totali": "30",
    })
    assert r.status_code == 200, r.text
    rows = _rows(client, set(classi))
    assert {x["classe_id"] for x in rows} == set(classi)
    assert all(len(x["partner_classe_ids"]) == 3 and len(x["partner_assignment_ids"]) == 3 for x in rows)

    # eliminare una riga elimina tutto il gruppo
    client.delete(f"/api/assignments/{rows[0]['assignment_id']}")
    assert not _rows(client, set(classi))


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


def test_scaling_hits_only_the_entity_of_the_lesson(client, school_setup):
    """Scalata mirata: le ore di lezione in coppia scalano solo il monte ore della coppia, quelle
    singole solo il monte ore della singola, anche con stesso docente e stessa classe."""
    from datetime import date
    from app.database import SessionLocal
    from app.models import OrarioSettimanale, SlotLezione
    from app.services.schedule import ScheduleService

    docente_id = next(iter(school_setup["teachers_by_name"].values()))
    a = client.post("/api/classes", json={"nome": "5Y"}).json()["classe_id"]
    b = client.post("/api/classes", json={"nome": "5Z"}).json()["classe_id"]
    pairing_id = client.post("/api/class-pairings", json={"classe_a_id": a, "classe_b_id": b}).json()["pairing_id"]
    client.post("/api/assignments", json={"docente_id": docente_id, "accoppiamento_id": pairing_id, "ore_totali": "40"})
    client.post("/api/assignments", json={"docente_id": docente_id, "classe_id": a, "ore_totali": "25"})
    rows = {(x["classe_id"], x["singola"]): x for x in client.get("/api/assignments").json() if x["classe_id"] in (a, b)}
    coppia_materia = next(x["materia_id"] for x in client.get("/api/assignments").json() if x["classe_id"] == a and not x["singola"])
    singola_materia = next(x["materia_id"] for x in client.get("/api/assignments").json() if x["classe_id"] == a and x["singola"])

    db = SessionLocal()
    try:
        orario = OrarioSettimanale(scuola_id="sch_1", settimana_inizio=date(2026, 3, 2))
        db.add(orario)
        db.flush()
        for ora, (materia, accoppiata) in enumerate([(coppia_materia, True)] * 3 + [(singola_materia, False)] * 2):
            db.add(SlotLezione(
                orario_settimanale_id=orario.id, classe_id=a, docente_id=docente_id, materia_id=materia,
                giorno="LUNEDI", ora_inizio=8 + ora, ora_fine=9 + ora, accoppiata=accoppiata,
            ))
        db.flush()
        ScheduleService(db).scale_monte_ore("sch_1", orario)
        db.commit()
    finally:
        db.close()

    now = {(x["classe_id"], x["singola"]): x for x in client.get("/api/assignments").json() if x["classe_id"] in (a, b)}
    assert now[(a, False)]["ore_erogate"] == 3  # coppia: 3 ore
    assert now[(a, True)]["ore_erogate"] == 2   # singola della stessa classe: 2 ore
    assert now[(b, False)]["ore_erogate"] == 0  # la classe partner non c'entra
    assert now[(a, False)]["ore_totali"] == 40 and now[(a, True)]["ore_totali"] == 25
