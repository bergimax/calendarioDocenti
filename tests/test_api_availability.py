"""End-to-end tests for the /api/availability routes."""

from datetime import date, timedelta


def test_list_weeks_endpoint(client, school_setup):
    """
    Regression test: GET /api/availability/weeks didn't exist at all, so
    the week selector on both the Disponibilità and Orario pages (which
    both fetch this) was always empty.
    """
    r = client.get("/api/availability/weeks")
    assert r.status_code == 200
    weeks = r.json()["weeks"]

    assert weeks, "expected at least one week in the anno formativo"
    assert weeks[0]["week_num"] == 1
    assert [w["week_num"] for w in weeks] == list(range(1, len(weeks) + 1))
    for w in weeks:
        assert date.fromisoformat(w["start"]).weekday() == 0  # Monday
        assert date.fromisoformat(w["end"]) == date.fromisoformat(w["start"]) + timedelta(days=4)

    # The fixture's own week_start (2026-04-06, within data_inizio_anno
    # 2026-01-01..data_fine_anno 2026-06-30) must be one of them.
    assert school_setup["week_start"] in {w["start"] for w in weeks}


def test_list_teachers_endpoint(client, school_setup):
    """
    Regression test: GET /api/teachers didn't exist, so the Disponibilità
    page's teacher grid was always empty.
    """
    r = client.get("/api/teachers")
    assert r.status_code == 200
    teachers = r.json()

    by_name = {t["nome"]: t for t in teachers}
    assert set(by_name) == set(school_setup["teachers_by_name"])
    for nome, teacher_id in school_setup["teachers_by_name"].items():
        assert by_name[nome]["teacher_id"] == teacher_id
    assert by_name["Prof Alfa"]["tipo"] == "ASSUNTO"
    assert by_name["Prof Beta"]["tipo"] == "CONTRATTO"


def test_new_teacher_gets_default_grid(client, school_setup):
    teacher_id = next(iter(school_setup["teachers_by_name"].values()))
    week = school_setup["week_start"]

    r = client.get(f"/api/availability/{week}/{teacher_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["is_default"] is True
    assert set(body["giorni_fasce"].keys()) == {"lunedi", "martedi", "mercoledi", "giovedi", "venerdi"}


def test_save_and_retrieve_availability(client, school_setup):
    teacher_id = next(iter(school_setup["teachers_by_name"].values()))
    week = school_setup["week_start"]

    grid = client.get(f"/api/availability/{week}/{teacher_id}").json()["giorni_fasce"]
    grid["lunedi"][0]["disponibile"] = False

    r = client.post(f"/api/availability/{week}/{teacher_id}", json={"giorni_fasce": grid})
    assert r.status_code == 200
    assert r.json()["status"] == "saved"

    r = client.get(f"/api/availability/{week}/{teacher_id}")
    assert r.json()["giorni_fasce"]["lunedi"][0]["disponibile"] is False
    assert r.json().get("is_default", False) is False


def test_save_availability_rejects_incomplete_grid(client, school_setup):
    teacher_id = next(iter(school_setup["teachers_by_name"].values()))
    week = school_setup["week_start"]

    r = client.post(f"/api/availability/{week}/{teacher_id}", json={"giorni_fasce": {"lunedi": []}})
    assert r.status_code == 400


def test_status_endpoint_is_not_shadowed_by_teacher_route(client, school_setup):
    """
    Regression test: GET /availability/{week}/status used to be registered
    after GET /availability/{week}/{teacher_id}, so FastAPI matched "status"
    as a teacher_id and this endpoint was unreachable.
    """
    week = school_setup["week_start"]
    r = client.get(f"/api/availability/{week}/status")
    assert r.status_code == 200
    body = r.json()
    assert body["total_teachers"] == len(school_setup["teachers_by_name"])
    assert "ready_to_generate" in body


def test_unknown_teacher_is_a_clean_client_error(client, school_setup):
    week = school_setup["week_start"]
    r = client.get(f"/api/availability/{week}/does-not-exist")
    assert r.status_code in (400, 404)


def test_copy_from_previous_week(client, school_setup):
    teacher_id = next(iter(school_setup["teachers_by_name"].values()))
    week = school_setup["week_start"]
    prev_week = "2026-03-30"

    client.post(f"/api/availability/{prev_week}/{teacher_id}", json={
        "giorni_fasce": client.get(f"/api/availability/{prev_week}/{teacher_id}").json()["giorni_fasce"]
    })

    r = client.post(f"/api/availability/{week}/copy-from/{prev_week}")
    assert r.status_code == 200
    assert r.json()["teachers_copied"] == 1
