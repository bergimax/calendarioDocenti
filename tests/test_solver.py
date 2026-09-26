"""
Unit tests for the OR-Tools solver, built directly from a ScheduleContext
(no DB involved) so scenarios can be crafted precisely.
"""

from datetime import date

from app.domain.solver import (
    ScheduleSolver,
    ScheduleContext,
    AssegnazioneDati,
    DisponibilitaDati,
    CalendarioDati,
)


def _full_availability(days=("lunedi", "martedi", "mercoledi", "giovedi", "venerdi")):
    return {
        day: [
            {"ora_inizio": f"{h:02d}:00", "ora_fine": f"{h + 1:02d}:00", "disponibile": True}
            for h in range(8, 14)
        ]
        for day in days
    }


def test_build_and_solve_does_not_raise():
    """
    Regression test: build_model() used to crash on every call because
    CpModel.NumConstraints() doesn't exist in the installed ortools API, and
    _soft_contractor_gaps compared unsolved CP-SAT variables with `== 1`
    inside a Python `any()` (raises NotImplementedError before solving).
    """
    ctx = _minimal_context()
    solver = ScheduleSolver(ctx)
    solver.build_model()  # must not raise
    status = solver.solve(timeout_seconds=10)
    assert status in ("OPTIMAL", "FEASIBLE")


def _minimal_context(**overrides):
    assegnazioni = overrides.get(
        "assegnazioni",
        [
            AssegnazioneDati(
                "a1", "d1", "Prof Rossi", "ASSUNTO", "c1", "1A", "m1", "Matematica",
                "TEORIA", "ALTO", ore_residue=30,
            ),
        ],
    )
    # 30 = 6h/giorno x 5 giorni: the classe's day capacity is now a hard
    # == (see _constraint_day_capacity), so a full week's fill must be
    # actually reachable given ore_residue, not just an upper bound.
    calendario = overrides.get(
        "calendario",
        [CalendarioDati(date(2026, 4, 6 + g), g, ore_max_giornata=6) for g in range(5)],
    )
    return ScheduleContext(
        scuola_id="sch_1",
        week_start=date(2026, 4, 6),
        week_end=date(2026, 4, 13),
        anno_fine=overrides.get("anno_fine", date(2026, 6, 30)),
        assegnazioni=assegnazioni,
        disponibilita_map=overrides.get("disponibilita_map", {}),
        calendario=calendario,
        classi_accoppiate=overrides.get("classi_accoppiate", []),
        docenti_map=overrides.get("docenti_map", {"d1": "ASSUNTO"}),
        classi_set=overrides.get("classi_set", {"c1"}),
        materie_map=overrides.get("materie_map", {"m1": "TEORIA"}),
    )


def test_closure_day_gets_zero_slots():
    """Regression test: flag_chiusura must exclude that day from scheduling (specs.md 3.1/4.1)."""
    calendario = [
        CalendarioDati(date(2026, 4, 6), 0, ore_max_giornata=6, flag_chiusura=True),
        *[CalendarioDati(date(2026, 4, 6 + g), g, ore_max_giornata=6) for g in range(1, 5)],
    ]
    ctx = _minimal_context(calendario=calendario)
    solver = ScheduleSolver(ctx)
    solver.build_model()
    solver.solve(timeout_seconds=10)
    slots = solver.extract_solution()
    assert not any(s["giorno"] == "LUNEDI" for s in slots)


def test_stage_day_excludes_only_that_class():
    """Hard constraint 5 (specs.md 3.2/4.1): a class in stage gets no lessons that day."""
    assegnazioni = [
        AssegnazioneDati("a1", "d1", "Prof Rossi", "ASSUNTO", "c1", "1A", "m1", "Matematica",
                          "TEORIA", "ALTO", ore_residue=10),
        AssegnazioneDati("a2", "d1", "Prof Rossi", "ASSUNTO", "c2", "1B", "m1", "Matematica",
                          "TEORIA", "ALTO", ore_residue=10),
    ]
    calendario = [
        CalendarioDati(date(2026, 4, 6), 0, ore_max_giornata=6, flag_stage_classe_id="c1"),
        *[CalendarioDati(date(2026, 4, 6 + g), g, ore_max_giornata=6) for g in range(1, 5)],
    ]
    ctx = _minimal_context(
        assegnazioni=assegnazioni, calendario=calendario, classi_set={"c1", "c2"}
    )
    solver = ScheduleSolver(ctx)
    solver.build_model()
    solver.solve(timeout_seconds=10)
    slots = solver.extract_solution()
    assert not any(s["classe_id"] == "c1" and s["giorno"] == "LUNEDI" for s in slots)


def test_paired_classes_scheduled_with_shared_teacher():
    """
    Regression test for the bug where _constraint_no_double_booking and
    _constraint_paired_classes contradicted each other whenever the same
    docente correctly teaches both sides of a classe-accoppiata (the
    spec-mandated case, specs.md 4.1.3): the pair was always forced to 0
    hours. It must now actually get scheduled, with both classes sharing the
    same docente at the same giorno/ora.
    """
    assegnazioni = [
        AssegnazioneDati("a1", "d1", "Prof Rossi", "ASSUNTO", "c1", "1A", "m1", "Matematica",
                          "TEORIA", "ALTO", ore_residue=20),
        AssegnazioneDati("a2", "d1", "Prof Rossi", "ASSUNTO", "c2", "1B", "m1", "Matematica",
                          "TEORIA", "ALTO", ore_residue=20),
    ]
    ctx = _minimal_context(
        assegnazioni=assegnazioni,
        classi_accoppiate=[("c1", "c2", "m1")],
        classi_set={"c1", "c2"},
    )
    solver = ScheduleSolver(ctx)
    solver.build_model()
    status = solver.solve(timeout_seconds=15)
    assert status in ("OPTIMAL", "FEASIBLE")

    slots = solver.extract_solution()
    assert len(slots) > 0, "paired lesson must not be forced to zero hours"

    by_time = {}
    for s in slots:
        by_time.setdefault((s["giorno"], s["ora_inizio"]), []).append(s)

    for (giorno, ora), pair in by_time.items():
        assert len(pair) == 2, f"expected both classes at {giorno} {ora}, got {pair}"
        docenti = {s["docente_id"] for s in pair}
        assert docenti == {"d1"}, "both sides of a paired lesson must share the same docente"
        classi = {s["classe_id"] for s in pair}
        assert classi == {"c1", "c2"}


def test_contratto_without_availability_gets_no_slots():
    """Hard constraint 4: a CONTRATTO teacher with no availability record is unavailable."""
    assegnazioni = [
        AssegnazioneDati("a1", "d2", "Prof Bianchi", "CONTRATTO", "c1", "1A", "m2", "Lab",
                          "PRATICA", "MEDIO", ore_residue=10),
    ]
    ctx = _minimal_context(
        assegnazioni=assegnazioni,
        disponibilita_map={},
        docenti_map={"d2": "CONTRATTO"},
        materie_map={"m2": "PRATICA"},
    )
    solver = ScheduleSolver(ctx)
    solver.build_model()
    solver.solve(timeout_seconds=10)
    slots = solver.extract_solution()
    assert slots == []


def test_contratto_availability_is_respected():
    """A CONTRATTO teacher can only be scheduled in slots marked disponibile=True."""
    disponibilita = DisponibilitaDati("d2", _full_availability())
    # Mark every slot unavailable except Tuesday 08:00-09:00
    for day, slots in disponibilita.giorni_fasce.items():
        for slot in slots:
            slot["disponibile"] = day == "martedi" and slot["ora_inizio"] == "08:00"

    assegnazioni = [
        AssegnazioneDati("a1", "d2", "Prof Bianchi", "CONTRATTO", "c1", "1A", "m2", "Lab",
                          "PRATICA", "MEDIO", ore_residue=10),
    ]
    ctx = _minimal_context(
        assegnazioni=assegnazioni,
        disponibilita_map={"d2": disponibilita},
        docenti_map={"d2": "CONTRATTO"},
        materie_map={"m2": "PRATICA"},
    )
    solver = ScheduleSolver(ctx)
    solver.build_model()
    solver.solve(timeout_seconds=10)
    slots = solver.extract_solution()
    for s in slots:
        assert s["giorno"] == "MARTEDI" and s["ora_inizio"] == 8


def test_monte_ore_limit_is_not_exceeded():
    """Hard constraint 6: total scheduled hours for an assegnazione can't exceed ore_residue."""
    assegnazioni = [
        AssegnazioneDati("a1", "d1", "Prof Rossi", "ASSUNTO", "c1", "1A", "m1", "Matematica",
                          "TEORIA", "ALTO", ore_residue=3),
    ]
    ctx = _minimal_context(assegnazioni=assegnazioni)
    solver = ScheduleSolver(ctx)
    solver.build_model()
    solver.solve(timeout_seconds=10)
    slots = solver.extract_solution()
    assert len(slots) <= 3


def test_pratica_hours_scattered_across_a_day_score_worse_than_a_block():
    """
    Hard constraint 2e, relaxable (specs.md 4.1: PRATICA/laboratorio hours
    should form blocchi da 3 a 6 ore; admin decision 2026-09-23: "almeno 3
    ore di laboratorio di fila, oppure nulla" - promoted from a plain soft
    preference to a near-hard requirement with an override var at
    RELAX_WEIGHT). Compare the same 3 total hours laid out as three
    isolated single hours vs. one contiguous block: the block must score
    strictly higher, and only the scattered layout should surface a
    "pratica_block_override" conflict (the override the solver was forced
    to take to keep those fixed, non-contiguous hours feasible).
    """
    assegnazioni = [
        AssegnazioneDati("a1", "d1", "Prof Bianchi", "ASSUNTO", "c1", "1A", "m2", "Lab",
                          "PRATICA", "MEDIO", ore_residue=20),
    ]
    ctx = _minimal_context(assegnazioni=assegnazioni, materie_map={"m2": "PRATICA"})

    scattered = ScheduleSolver(ctx)
    scattered.build_model()
    assert scattered.solve_fixed({("a1", 0, 0), ("a1", 0, 2), ("a1", 0, 4)}) in ("OPTIMAL", "FEASIBLE")
    scattered_score, _, _ = scattered.calculate_quality_score()

    contiguous = ScheduleSolver(ctx)
    contiguous.build_model()
    assert contiguous.solve_fixed({("a1", 0, 0), ("a1", 0, 1), ("a1", 0, 2)}) in ("OPTIMAL", "FEASIBLE")
    contiguous_score, _, _ = contiguous.calculate_quality_score()

    assert contiguous_score > scattered_score
    assert any(c["conflict_id"].startswith("pratica_block_override") for c in scattered.get_conflicts())
    assert not any(c["conflict_id"].startswith("pratica_block") for c in contiguous.get_conflicts())


def test_pratica_short_isolated_hour_is_flagged_too_short():
    """A single isolated practice hour (below the 3h minimum) must be
    flagged, even though it has no internal gaps to catch."""
    assegnazioni = [
        AssegnazioneDati("a1", "d1", "Prof Bianchi", "ASSUNTO", "c1", "1A", "m2", "Lab",
                          "PRATICA", "MEDIO", ore_residue=20),
        # Fills every other classroom hour of the week for c1, so the
        # classe's day capacity (now a hard ==, see _constraint_day_capacity)
        # is satisfied while day_cap - and so _soft_pratica_blocks' own
        # min(3, day_cap) threshold - stays a normal 6h day, not an
        # artificially short one.
        AssegnazioneDati("a2", "d1", "Prof Bianchi", "ASSUNTO", "c1", "1A", "m1", "Matematica",
                          "TEORIA", "ALTO", ore_residue=29),
    ]
    ctx = _minimal_context(
        assegnazioni=assegnazioni, materie_map={"m1": "TEORIA", "m2": "PRATICA"},
    )
    assigned_keys = {("a1", 0, 0)} | {
        ("a2", g, h) for g in range(5) for h in range(6) if not (g == 0 and h == 0)
    }

    solver = ScheduleSolver(ctx)
    solver.build_model()
    assert solver.solve_fixed(assigned_keys) in ("OPTIMAL", "FEASIBLE")

    conflicts = solver.get_conflicts()
    assert any(c["conflict_id"].startswith("pratica_block_override") for c in conflicts)


def test_soft_constraint_weights_are_applied_to_objective():
    """
    Regression test: build_model()'s objective used to be
    `sum(penalty for penalty, _ in self.soft_penalties)`, silently dropping
    the per-constraint `weight` so every soft violation counted as 1
    regardless of its documented weight (10/8/15/12). The CP-SAT objective's
    linear coefficients must reflect those weights, not be uniformly 1.
    """
    ctx = _minimal_context()
    solver = ScheduleSolver(ctx)
    solver.build_model()

    assert solver.soft_penalties, "expected at least one soft constraint to be registered"
    weights_used = {p.weight for p in solver.soft_penalties}
    assert weights_used != {1}, "soft constraints should use their documented weights, not all 1"

    objective_coeffs = set(solver.model.Proto().objective.coeffs)
    assert objective_coeffs != {1}, "objective coefficients must include the real weights"
    assert objective_coeffs & weights_used, "objective should be built from the registered weights"


def _short_on_hours_context():
    """One classe, 6h/day required, but the only docente has just 3h left."""
    assegnazioni = [
        AssegnazioneDati("a1", "d1", "Prof Rossi", "ASSUNTO", "c1", "1A", "m1", "Matematica",
                          "TEORIA", "ALTO", ore_residue=3),
    ]
    return _minimal_context(assegnazioni=assegnazioni)


def test_strict_model_is_infeasible_when_hours_cannot_fill_the_week():
    solver = ScheduleSolver(_short_on_hours_context())
    solver.build_model()
    assert solver.solve(timeout_seconds=10) == "INFEASIBLE"


def test_best_effort_returns_fullest_schedule_and_reports_empty_hours():
    solver = ScheduleSolver(_short_on_hours_context(), best_effort=True)
    solver.build_model()
    assert solver.solve(timeout_seconds=10) in ("OPTIMAL", "FEASIBLE")

    slots = solver.extract_solution()
    assert len(slots) == 3  # every hour the docente has left is used

    unfilled = [c for c in solver.get_conflicts() if c.get("ore")]
    assert unfilled, "uncovered hours must come back as conflicts"
    # each classe/day is short by 6 minus the lessons it got that day
    for c in unfilled:
        lessons = sum(1 for s in slots if s["giorno"] == c["giorno"])
        assert len(c["ore"]) == 6 - lessons
        assert all(8 <= h <= 13 for h in c["ore"])
        assert not any(s["giorno"] == c["giorno"] and s["ora_inizio"] in c["ore"] for s in slots)


def test_calendar_day_longer_than_the_grid_is_capped_at_six_hours():
    """An 8h calendar day can't be filled with 6 hourly slots: cap, don't go INFEASIBLE."""
    calendario = [CalendarioDati(date(2026, 4, 6 + g), g, ore_max_giornata=8) for g in range(5)]
    solver = ScheduleSolver(_minimal_context(calendario=calendario))
    solver.build_model()
    assert solver.solve(timeout_seconds=10) in ("OPTIMAL", "FEASIBLE")
