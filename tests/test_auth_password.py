"""Changing one's own password via POST /api/auth/change-password (real login, no auth bypass)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import Admin, Scuola
from app.security import hash_password


@pytest.fixture
def real_client():
    # No admin-auth override here: this exercises the real login/session.
    db = SessionLocal()
    try:
        db.add(Scuola(
            id="sch_1", nome="S", anno_formativo="2026-2027",
            data_inizio_anno=date(2026, 9, 1), data_fine_anno=date(2027, 6, 30),
        ))
        db.flush()
        db.add(Admin(scuola_id="sch_1", email="pw@example.com", password_hash=hash_password("vecchiaPass1")))
        db.commit()
    finally:
        db.close()
    return TestClient(app)


def _login(client, password):
    return client.post("/api/auth/login", json={"email": "pw@example.com", "password": password})


def test_change_password_flow(real_client):
    c = real_client
    t1 = _login(c, "vecchiaPass1").json()["token"]
    t2 = _login(c, "vecchiaPass1").json()["token"]  # a second session
    h1 = {"Authorization": f"Bearer {t1}"}

    def change(cur, new):
        return c.post("/api/auth/change-password", headers=h1, json={"current_password": cur, "new_password": new})

    assert change("sbagliata", "nuovaPass99").status_code == 400
    assert change("vecchiaPass1", "corta").status_code == 400
    assert change("vecchiaPass1", "vecchiaPass1").status_code == 400
    assert change("vecchiaPass1", "nuovaPass99").status_code == 200

    assert _login(c, "vecchiaPass1").status_code == 401
    assert _login(c, "nuovaPass99").status_code == 200
    # the session used for the change survives, the other one is closed
    assert c.get("/api/auth/me", headers=h1).status_code == 200
    assert c.get("/api/auth/me", headers={"Authorization": f"Bearer {t2}"}).status_code == 401


def test_change_password_requires_login(real_client):
    r = real_client.post("/api/auth/change-password", json={"current_password": "a", "new_password": "bbbbbbbb"})
    assert r.status_code == 401
