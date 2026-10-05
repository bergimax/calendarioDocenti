"""Role-based access: SEGRETERIA reads the schedule and edits docenti
availability, but cannot generate/modify schedules or change school data."""

import pytest

from app.models import Admin
from app.security import get_current_admin

WEEK = "2026-10-05"


@pytest.fixture
def segreteria(client):
    from app.main import app

    app.dependency_overrides[get_current_admin] = lambda: Admin(
        id="seg_test", email="segreteria@example.com", role="SEGRETERIA"
    )
    yield client
    # the `client` fixture pops the override on teardown


def test_segreteria_cannot_generate_or_change_schedule(segreteria):
    for path in (
        f"/api/schedule/generate",
        f"/api/schedule/{WEEK}/regenerate",
        f"/api/schedule/{WEEK}/approve",
        f"/api/schedule/{WEEK}/modify-slot",
        f"/api/schedule/{WEEK}/assign-slot",
        f"/api/schedule/{WEEK}/feedback",
    ):
        r = segreteria.post(path, json={"week_start": WEEK})
        assert r.status_code == 403, (path, r.status_code)


def test_segreteria_cannot_use_setup_chat_dati_writes_or_teacher_crud(segreteria):
    assert segreteria.post("/api/setup/save", json={}).status_code == 403
    assert segreteria.post("/api/chat/send", json={}).status_code == 403
    assert segreteria.get("/api/soft-weights").status_code == 403
    assert segreteria.post("/api/classes", json={"nome": "X"}).status_code == 403
    assert segreteria.delete("/api/classes/x").status_code == 403
    assert segreteria.post("/api/teachers", json={"nome": "X"}).status_code == 403
    assert segreteria.put("/api/teachers/x", json={}).status_code == 403
    assert segreteria.delete("/api/teachers/x").status_code == 403


def test_segreteria_can_view_schedule_and_edit_availability(segreteria):
    # Reads are allowed (404 = no schedule for that week, not a permission error).
    assert segreteria.get(f"/api/schedule/{WEEK}").status_code != 403
    assert segreteria.get(f"/api/schedule/{WEEK}/export-pdf").status_code != 403
    assert segreteria.get("/api/teachers").status_code == 200
    assert segreteria.get("/api/classes").status_code == 200
    # Availability writes are allowed (not blocked by the role check).
    r = segreteria.post(f"/api/availability/{WEEK}/some-teacher", json={"giorni_fasce": {}})
    assert r.status_code != 403
    r = segreteria.post(f"/api/availability/{WEEK}/copy-from/2026-09-28")
    assert r.status_code != 403


def test_admin_role_is_not_restricted(client):
    # The default test user has no role -> treated as a full admin.
    assert client.get("/api/soft-weights").status_code == 200
    assert client.post("/api/classes", json={"nome": "Test"}).status_code != 403
