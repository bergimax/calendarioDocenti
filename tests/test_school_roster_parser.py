"""
Tests for SchoolRosterParser (app/domain/parser.py), used by
scripts/import_documenti.py to bootstrap docenti/classi/associations from
this school's real PDFs.
"""

import io

import pytest

reportlab = pytest.importorskip("reportlab")
from reportlab.lib import colors  # noqa: E402
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle  # noqa: E402

from app.domain.parser import SchoolRosterParser  # noqa: E402


def _bordered_table_pdf(rows):
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=(700, 800))
    table = Table(rows)
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)]))
    doc.build([table])
    return buf.getvalue()


def test_parse_elenco_docenti_pdf_extracts_roster_and_skips_lab_rows():
    pdf_bytes = _bordered_table_pdf([
        ["BELLINI IPPOLITA", "LABORATORIO 38 (Lab. Estetico)", "II piano"],
        ["BERGI MASSIMO", "AULA 32", "II piano"],
        ["LAB. INFORMATICO", "AULA 31", "II piano"],
    ])

    entries = SchoolRosterParser.parse_elenco_docenti_pdf(pdf_bytes)

    assert len(entries) == 2
    by_cognome = {e["cognome"]: e for e in entries}
    assert by_cognome["BELLINI"]["nome_completo"] == "BELLINI IPPOLITA"
    assert by_cognome["BELLINI"]["aula"] == "LABORATORIO 38 (Lab. Estetico)"
    assert by_cognome["BERGI"]["piano"] == "II piano"
    assert "LAB. INFORMATICO" not in by_cognome


@pytest.mark.parametrize("nome_classe,expected_gruppo", [
    ("I ELETTRICISTI", "PRIME"),
    ("II OP. INFORM.", "SECONDE"),
    ("III ESTETISTE", "TERZE"),
    ("IV PAN. E PAST.", "QUARTE"),
    ("I I.T.C.", "PRIMA4+2"),
    ("classe senza numero romano", None),
])
def test_classe_gruppo_inference(nome_classe, expected_gruppo):
    assert SchoolRosterParser._classe_gruppo(nome_classe) == expected_gruppo


@pytest.mark.parametrize("raw,expected", [
    ("lunedì", "lunedi"),
    ("mmaarrtteeddìì", "martedi"),  # doubled-letter artifact seen in the real PDF
    ("ggiioovveeddìì", "giovedi"),
    ("vveenneerrddìì", "venerdi"),
    ("", None),
    (None, None),
    ("qualcos'altro", None),
])
def test_normalize_giorno(raw, expected):
    assert SchoolRosterParser._normalize_giorno(raw) == expected


def test_parse_orario_settimanale_pdf_extracts_classi_and_slots():
    header = ["DATA", "Orario", "I ELETTRICISTI", "II ELETTRICISTI"]
    rows = [
        header,
        ["lunedì", "8-9", "ROSSI", "BIANCHI"],
        [None, "9-10", "ROSSI", ""],
        ["martedì", "8-9", "", "BIANCHI"],
    ]
    pdf_bytes = _bordered_table_pdf(rows)

    result = SchoolRosterParser.parse_orario_settimanale_pdf(pdf_bytes)

    classi_by_nome = {c["nome"]: c["gruppo"] for c in result["classi"]}
    assert classi_by_nome == {"I ELETTRICISTI": "PRIME", "II ELETTRICISTI": "SECONDE"}

    slots = result["slots"]
    assert {"classe_nome": "I ELETTRICISTI", "giorno": "lunedi", "ora_inizio": 8, "docente_cognome": "ROSSI"} in slots
    assert {"classe_nome": "II ELETTRICISTI", "giorno": "lunedi", "ora_inizio": 8, "docente_cognome": "BIANCHI"} in slots
    assert {"classe_nome": "I ELETTRICISTI", "giorno": "lunedi", "ora_inizio": 9, "docente_cognome": "ROSSI"} in slots
    # blank cell (II ELETTRICISTI, lunedì 9-10) must not produce a slot
    assert not any(s["giorno"] == "lunedi" and s["ora_inizio"] == 9 and s["classe_nome"] == "II ELETTRICISTI" for s in slots)
    # day carried forward correctly onto martedì
    assert {"classe_nome": "II ELETTRICISTI", "giorno": "martedi", "ora_inizio": 8, "docente_cognome": "BIANCHI"} in slots
