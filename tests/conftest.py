"""
Shared pytest fixtures.

Tests run against a real SQLite file (not Postgres) so the whole stack -
FastAPI routes, services, repositories, SQLAlchemy models and the OR-Tools
solver - is exercised end-to-end without needing a running database server.
The DATABASE_URL env var must be set before `app.database`/`app.config` are
first imported, so it happens at module import time here, before any other
test module can import `app.*`.
"""

import os
import tempfile

import pytest

_db_fd, _db_path = tempfile.mkstemp(prefix="calendariodocenti_test_", suffix=".db")
os.close(_db_fd)
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

from app.database import Base, engine  # noqa: E402
import app.models  # noqa: E402,F401  (registers all models on Base.metadata)


def pytest_sessionfinish(session, exitstatus):
    try:
        os.remove(_db_path)
    except OSError:
        pass


@pytest.fixture(autouse=True)
def fresh_database():
    """Every test starts with an empty schema (single-tenant app, one 'sch_1' school)."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    # The setup wizard keeps an in-progress SetupService as a module-level
    # singleton (see app/routes/setup.py) - reset it so tests don't leak
    # cached setup data into each other.
    import app.routes.setup as setup_routes
    setup_routes._setup_service = None

    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import Admin
    from app.security import get_current_admin

    # Every /api router requires an admin session (app/security.py); these
    # tests exercise the routes, not the login, so bypass it.
    app.dependency_overrides[get_current_admin] = lambda: Admin(id="admin_test", email="test@example.com")
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_current_admin, None)


@pytest.fixture
def setup_file_data():
    """
    A small but representative setup dataset:
    - 2 docenti (one ASSUNTO, one CONTRATTO with no email)
    - 2 classi (1A, 1B) paired on "Matematica" taught by the same docente
      (the spec-mandated case for classi accoppiate, see specs.md 4.1.3)
    - a 5-day calendar with Monday flagged as a closure (flag_chiusura)
    """
    return {
        "docenti": "nome,email,tipo\nProf Alfa,alfa@x.it,ASSUNTO\nProf Beta,,CONTRATTO\n",
        "classi": "nome,n_studenti\n1A,20\n1B,22\n",
        "materie": "nome,tipo,peso_cognitivo\nMatematica,TEORIA,ALTO\nLab,PRATICA,MEDIO\n",
        "assegnazioni": (
            "docente_nome,classe_nome,materia_nome,ore_anno\n"
            "Prof Alfa,1A,Matematica,90\n"
            "Prof Alfa,1B,Matematica,90\n"
            "Prof Beta,1A,Lab,60\n"
        ),
        "accoppiamenti": "classe_a,classe_b,materia_nome,note\n1A,1B,Matematica,congiunta\n",
        "calendario": (
            "data,ore_max_giornata,flag_chiusura,stage_classe_id\n"
            "2026-04-06,6,true,\n"
            "2026-04-07,6,false,\n"
            "2026-04-08,6,false,\n"
            "2026-04-09,6,false,\n"
            "2026-04-10,6,false,\n"
        ),
    }


@pytest.fixture
def school_setup(client, setup_file_data):
    """Runs the full setup flow via the real API and returns useful ids."""
    r = client.post("/api/setup/validate", json=setup_file_data)
    assert r.status_code == 200, r.text
    assert r.json()["can_proceed"] is True, r.json()

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
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "setup_complete"
    assert body["school_id"] == "sch_1"

    from app.database import SessionLocal
    from app.models import Docente

    db = SessionLocal()
    try:
        docenti = db.query(Docente).filter_by(scuola_id="sch_1").all()
        teachers_by_name = {d.nome: d.id for d in docenti}
    finally:
        db.close()

    return {
        "school_id": "sch_1",
        "week_start": "2026-04-06",  # the Monday from setup_file_data, flagged as closure
        "teachers_by_name": teachers_by_name,
    }
