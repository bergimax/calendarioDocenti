"""
End-to-end test: upload a PDF calendar, run it through the setup wizard, and
confirm the generated schedule actually respects the per-year-group daily
hours it encodes (not just a single school-wide value).
"""

import io

import pytest

reportlab = pytest.importorskip("reportlab")
from reportlab.pdfgen import canvas  # noqa: E402


def _build_calendar_pdf(rows, col_x):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(600, 800))
    c.setFont("Helvetica", 8)
    y = 750
    for day, month, year, hours in rows:
        c.drawString(15, y, "gio"[:3])
        c.drawString(35, y, str(day))
        c.drawString(50, y, month)
        c.drawString(95, y, str(year))
        for gruppo, x in col_x.items():
            value = hours.get(gruppo)
            if value is not None:
                c.drawString(x, y, str(value))
        y -= 20
    c.showPage()
    c.save()
    return buf.getvalue()


def test_pdf_calendar_drives_per_class_day_capacity(client):
    from app.domain.parser import CALENDARIO_PDF_GRUPPI_COLONNE

    col_x = {gruppo: x_min + 5 for gruppo, (x_min, _) in CALENDARIO_PDF_GRUPPI_COLONNE}

    # A single school week: PRIME gets only 2 hours/day, SECONDE gets 6.
    pdf_bytes = _build_calendar_pdf(
        [
            (5, "ottobre", 2026, {"PRIME": 2, "SECONDE": 6}),
            (6, "ottobre", 2026, {"PRIME": 2, "SECONDE": 6}),
            (7, "ottobre", 2026, {"PRIME": 2, "SECONDE": 6}),
            (8, "ottobre", 2026, {"PRIME": 2, "SECONDE": 6}),
            (9, "ottobre", 2026, {"PRIME": 2, "SECONDE": 6}),
        ],
        col_x,
    )

    r = client.post(
        "/api/calendar/upload",
        files={"file": ("calendario.pdf", pdf_bytes, "application/pdf")},
    )
    assert r.status_code == 200, r.text
    preview = r.json()["preview"]
    # The other 3 known year-groups also get an entry (0h, blank cells), so
    # just check the two groups this test actually populates are present.
    assert {"PRIME", "SECONDE"} <= set(preview["gruppi"])

    file_data = {
        "docenti": "nome,email,tipo\nProf Alfa,alfa@x.it,ASSUNTO\n",
        "classi": "nome,n_studenti,gruppo\n1 Prima,20,PRIME\n1 Seconda,20,SECONDE\n",
        "materie": "nome,tipo,peso_cognitivo\nMatematica,TEORIA,ALTO\n",
        "assegnazioni": (
            "docente_nome,classe_nome,materia_nome,ore_anno\n"
            "Prof Alfa,1 Prima,Matematica,90\n"
            "Prof Alfa,1 Seconda,Matematica,90\n"
        ),
    }
    r = client.post("/api/setup/validate", json=file_data)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["can_proceed"] is True, body["results"]
    assert {"PRIME", "SECONDE"} <= set(body["results"]["calendario"]["preview"]["gruppi"])

    r = client.post(
        "/api/setup/save",
        json={
            "file_ids": [],
            "school_name": "Scuola PDF",
            "school_year": "2025-2026",
            "data_inizio": "2026-01-01",
            "data_fine": "2026-06-30",
        },
    )
    assert r.status_code == 200
    assert r.json()["status"] == "setup_complete"

    r = client.post("/api/schedule/generate", json={"week_start": "2026-10-05"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "generated"

    slots = body["slots"]
    from app.database import SessionLocal
    from app.models import Classe

    db = SessionLocal()
    try:
        prima_id = db.query(Classe).filter_by(scuola_id="sch_1", nome="1 Prima").first().id
        seconda_id = db.query(Classe).filter_by(scuola_id="sch_1", nome="1 Seconda").first().id
    finally:
        db.close()

    hours_by_day = {}
    for s in slots:
        if s["classe_id"] == prima_id:
            hours_by_day.setdefault((s["giorno"], "PRIME"), 0)
            hours_by_day[(s["giorno"], "PRIME")] += 1
        elif s["classe_id"] == seconda_id:
            hours_by_day.setdefault((s["giorno"], "SECONDE"), 0)
            hours_by_day[(s["giorno"], "SECONDE")] += 1

    # PRIME's PDF-derived cap (2h/day) must be respected...
    for (giorno, gruppo), n in hours_by_day.items():
        if gruppo == "PRIME":
            assert n <= 2, f"1 Prima exceeded its PDF-derived 2h/day cap on {giorno}: {n}"

    # ...and SECONDE, with a higher cap (6h/day), must be able to use more
    # hours than PRIME's cap would allow, proving the two aren't sharing one
    # school-wide value.
    max_seconda_day = max(
        (n for (_, gruppo), n in hours_by_day.items() if gruppo == "SECONDE"), default=0
    )
    assert max_seconda_day > 2
