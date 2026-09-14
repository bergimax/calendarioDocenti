"""
Tests for CalendarParser.parse_calendario_pdf.

Builds a tiny synthetic PDF at test time (via reportlab) that mimics the
"CALENDARIO AF" table layout this parser targets: a date in the left column
and 5 year-group hour columns at the same x-ranges as the real school
template (see CALENDARIO_PDF_GRUPPI_COLONNE in app/domain/parser.py). This
keeps the test independent of any real school's PDF file while still
exercising the actual position-based extraction logic.
"""

import io
from datetime import date

import pytest

reportlab = pytest.importorskip("reportlab")
from reportlab.pdfgen import canvas  # noqa: E402

from app.domain.parser import CalendarParser  # noqa: E402

# x0 positions inside each of the 5 group column ranges used by the parser.
COL_X = {"PRIME": 150, "SECONDE": 205, "TERZE": 260, "QUARTE": 315, "PRIMA4+2": 370}


def _build_calendar_pdf(rows):
    """
    rows: list of (weekday_name, day, month_name, year, {gruppo: ore or None})
    Each row is drawn on its own horizontal line so words share the same y.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(600, 800))
    c.setFont("Helvetica", 8)
    y = 750
    for weekday, day, month, year, hours in rows:
        # weekday name is drawn but not required/used by the parser - kept
        # short and well clear of the day number to avoid the two merging
        # into one pdfplumber "word" when the weekday text is long.
        c.drawString(15, y, weekday[:3])
        c.drawString(35, y, str(day))
        c.drawString(50, y, month)
        c.drawString(95, y, str(year))
        for gruppo, x in COL_X.items():
            value = hours.get(gruppo)
            if value is not None:
                c.drawString(x, y, str(value))
        y -= 20
    c.showPage()
    c.save()
    return buf.getvalue()


def test_parse_calendario_pdf_extracts_per_group_hours():
    pdf_bytes = _build_calendar_pdf([
        ("lunedi", 5, "ottobre", 2026, {"PRIME": 6, "SECONDE": 6, "TERZE": 6, "QUARTE": 6, "PRIMA4+2": 6}),
        ("martedi", 6, "ottobre", 2026, {"PRIME": 6, "SECONDE": None, "TERZE": 6, "QUARTE": 6, "PRIMA4+2": 6}),
        ("mercoledi", 7, "ottobre", 2026, {"PRIME": 5, "SECONDE": 5, "TERZE": 5, "QUARTE": 5, "PRIMA4+2": 5}),
        # 8 ottobre 2026 (giovedì) intentionally missing -> inferred closure
        ("venerdi", 9, "ottobre", 2026, {"PRIME": 4, "SECONDE": 4, "TERZE": 4, "QUARTE": 4, "PRIMA4+2": 4}),
    ])

    entries = CalendarParser.parse_calendario_pdf(pdf_bytes)

    by_key = {(e["data"], e["gruppo"]): e for e in entries}

    assert by_key[(date(2026, 10, 5), "PRIME")]["ore_max_giornata"] == 6
    assert by_key[(date(2026, 10, 5), "PRIME")]["flag_chiusura"] is False

    # Blank cell for SECONDE on 6 ottobre -> 0 hours, not a school-wide closure
    assert by_key[(date(2026, 10, 6), "SECONDE")]["ore_max_giornata"] == 0
    assert by_key[(date(2026, 10, 6), "TERZE")]["ore_max_giornata"] == 6

    assert by_key[(date(2026, 10, 7), "QUARTE")]["ore_max_giornata"] == 5
    assert by_key[(date(2026, 10, 9), "PRIMA4+2")]["ore_max_giornata"] == 4

    # 8 ottobre 2026 is a Thursday absent from every group -> inferred closure
    closure = by_key[(date(2026, 10, 8), None)]
    assert closure["flag_chiusura"] is True
    assert closure["ore_max_giornata"] == 0

    # No spurious closure for days that are actually in the table
    assert (date(2026, 10, 5), None) not in by_key


def test_parse_calendario_pdf_rejects_unrecognized_layout():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(600, 800))
    c.drawString(100, 700, "this is not a calendar table")
    c.showPage()
    c.save()

    with pytest.raises(ValueError):
        CalendarParser.parse_calendario_pdf(buf.getvalue())
