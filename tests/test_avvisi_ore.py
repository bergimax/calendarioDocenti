"""Ore del docente in più/in meno: avviso (cella gialla), non conflitto (cella rossa)."""

from app.domain.solver import AVVISO_KINDS
from app.services.schedule import ScheduleService


def _conflict(kind, chiave, avviso, **kw):
    return {"kind": kind, "chiave": chiave, "avviso": avviso, "classe_id": "c1", "docente_id": "d1", **kw}


def test_avviso_kinds_are_hours_off_target_only():
    assert AVVISO_KINDS == {"ore_target_deviation", "monte_ore_exceeded"}


def test_hours_off_target_marks_cell_as_avviso_not_conflitto():
    slots = [{"classe_id": "c1", "docente_id": "d1", "giorno": "LUNEDI", "ora_inizio": 8}]
    ScheduleService._mark_slot_conflicts(slots, [_conflict("ore_target_deviation", "k1", True)])
    assert slots[0]["conflitto"] is False
    assert slots[0]["avviso"] is True
    assert slots[0]["conflitto_chiavi"] == ["k1"]  # il messaggio resta raggiungibile al click


def test_real_conflict_stays_red_even_with_an_avviso_on_the_same_cell():
    slots = [{"classe_id": "c1", "docente_id": "d1", "giorno": "LUNEDI", "ora_inizio": 8}]
    ScheduleService._mark_slot_conflicts(slots, [
        _conflict("ore_target_deviation", "k1", True),
        _conflict("teoria_consecutive", "k2", False, giorno="LUNEDI"),
    ])
    assert slots[0]["conflitto"] is True
    assert slots[0]["avviso"] is False
    assert set(slots[0]["conflitto_chiavi"]) == {"k1", "k2"}


def test_paired_lesson_highlights_both_classes():
    """Conflitto/avviso di una classe accoppiata: evidenziate le celle di entrambe le classi."""
    slots = [
        {"classe_id": "c1", "classe_accoppiata_id": "c2", "docente_id": "d1", "giorno": "LUNEDI", "ora_inizio": 8},
        {"classe_id": "c2", "classe_accoppiata_id": "c1", "docente_id": "d1", "giorno": "LUNEDI", "ora_inizio": 8},
        {"classe_id": "c3", "docente_id": "d2", "giorno": "LUNEDI", "ora_inizio": 8},
    ]
    # avviso sulla sola classe c2 (ore del docente d1 in c2)
    ScheduleService._mark_slot_conflicts(slots, [_conflict("ore_target_deviation", "k1", True, classe_id="c2")])
    assert [s["avviso"] for s in slots] == [True, True, False]
