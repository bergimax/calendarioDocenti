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
                          "TEORIA", "ALTO", ore_residue=30),
        AssegnazioneDati("a2", "d1", "Prof Rossi", "ASSUNTO", "c2", "1B", "m1", "Matematica",
                          "TEORIA", "ALTO", ore_residue=30),
    ]
    ctx = _minimal_context(
        assegnazioni=assegnazioni,
        classi_accoppiate=[("c1", "c2", "m1", "d1")],
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


def test_schedule_with_a_freed_mid_day_hour_can_still_be_evaluated():
    """Admin "Rifiuta" leaves an hour free mid-day: evaluating the saved schedule must still work
    (allow_gaps), or every conflict silently disappears from the grid."""
    keys = {("a1", g, h) for g in range(5) for h in range(6) if (g, h) != (0, 2)}

    strict = ScheduleSolver(_minimal_context(), best_effort=True)
    strict.build_model()
    assert strict.solve_fixed(keys) == "INFEASIBLE"  # the "no gaps" rule rejects it

    evaluating = ScheduleSolver(_minimal_context(), best_effort=True, allow_gaps=True)
    evaluating.build_model()
    assert evaluating.solve_fixed(keys) in ("OPTIMAL", "FEASIBLE")


def test_forced_mode_reports_an_hour_outside_the_day_instead_of_rejecting_it():
    """A lesson forced beyond the calendar's day (ore_max 5, lesson at 13:00) is accepted in
    forced mode and reported as a classe_over_capacity conflict on that hour."""
    calendario = [CalendarioDati(date(2026, 4, 6 + g), g, ore_max_giornata=5) for g in range(5)]
    ctx = _minimal_context(calendario=calendario)
    keys = {("a1", g, h) for g in range(5) for h in range(6)}  # all 6 hours: one over the 5h day

    strict = ScheduleSolver(ctx, best_effort=True, allow_gaps=True)
    strict.build_model()
    assert strict.solve_fixed(keys) == "INFEASIBLE"

    forced = ScheduleSolver(ctx, forced=True)
    forced.build_model()
    assert forced.solve_fixed(keys) in ("OPTIMAL", "FEASIBLE")
    over = [c for c in forced.get_conflicts() if c["chiave"].startswith("classe_over_capacity")]
    assert over and all(c["ore_slot"] for c in over)


def _contractor_ctx(ore_residue, giorni_fasce):
    return _minimal_context(
        assegnazioni=[
            AssegnazioneDati(
                "a1", "d1", "Prof Rossi", "CONTRATTO", "c1", "1A", "m1", "Matematica",
                "TEORIA", "ALTO", ore_residue=ore_residue,
            ),
        ],
        docenti_map={"d1": "CONTRATTO"},
        disponibilita_map={"d1": DisponibilitaDati("d1", giorni_fasce)},
    )


def test_contractor_may_exceed_monte_ore():
    """A CONTRATTO docente is only bounded by availability, not by the monte ore."""
    ctx = _contractor_ctx(ore_residue=10, giorni_fasce=_full_availability())
    solver = ScheduleSolver(ctx)
    solver.build_model()
    assert solver.solve(timeout_seconds=10) in ("OPTIMAL", "FEASIBLE")
    assert len(solver.extract_solution()) == 30  # 6h x 5 days, > 10h of monte ore


def test_contractor_is_never_scheduled_when_unavailable():
    """
    A CONTRATTO docente is never placed in an hour they're unavailable, even
    if that leaves a classroom hour unfillable: the strict model is infeasible
    (the admin must then grant the override_availability deroga explicitly).
    """
    fasce = _full_availability()
    fasce["lunedi"][-1]["disponibile"] = False  # unavailable Monday 13:00
    ctx = _contractor_ctx(ore_residue=30, giorni_fasce=fasce)
    solver = ScheduleSolver(ctx)
    solver.build_model()
    assert solver.solve(timeout_seconds=10) == "INFEASIBLE"


def test_contractor_penalties_scale_with_scarcity_of_availability():
    """Little availability -> heavier target/gap penalties; plenty -> lighter."""
    def scarcity(fasce):
        solver = ScheduleSolver(_contractor_ctx(ore_residue=30, giorni_fasce=fasce))
        return solver._contractor_scarcity("d1")

    full = _full_availability()
    little = _full_availability(days=("lunedi",))  # 6h of 30
    assert scarcity(full) == 0.5
    assert scarcity(little) == 1.5 - 6 / 30
    assert scarcity(little) > scarcity(full)
    # not a contractor -> neutral
    assert ScheduleSolver(_minimal_context())._contractor_scarcity("d1") == 1.0


def _paired_hours_ctx(**overrides):
    """Due docenti coprono la stessa coppia c1+c2 in comune (una riga di accoppiamento
    ciascuno); altri due docenti tengono una classe ciascuno e riempiono il resto."""
    ass = []
    for did, nome in (("d1", "Prof Rossi"), ("d2", "Prof Verdi")):
        ass.append(AssegnazioneDati(f"{did}a", did, nome, "ASSUNTO", "c1", "1A", "m1", "Pratica",
                                    "TEORIA", "ALTO", ore_residue=60))
        ass.append(AssegnazioneDati(f"{did}b", did, nome, "ASSUNTO", "c2", "1B", "m1", "Pratica",
                                    "TEORIA", "ALTO", ore_residue=60))
    # due docenti singoli (uno per classe: un docente non può stare in due classi insieme)
    for cid, cn, did in (("c1", "1A", "d3"), ("c2", "1B", "d4")):
        ass.append(AssegnazioneDati(f"{did}{cid}", did, f"Prof {did}", "ASSUNTO", cid, cn, "m2", "Italiano",
                                    "TEORIA", "ALTO", ore_residue=240))
    return _minimal_context(
        assegnazioni=ass,
        classi_accoppiate=[("c1", "c2", "m1", "d1"), ("c1", "c2", "m1", "d2")],
        classi_set={"c1", "c2"},
        docenti_map={"d1": "ASSUNTO", "d2": "ASSUNTO", "d3": "ASSUNTO", "d4": "ASSUNTO"},
        materie_map={"m1": "TEORIA", "m2": "TEORIA"},
        **overrides,
    )


def test_docente_never_has_more_than_one_paired_hour_per_day():
    solver = ScheduleSolver(_paired_hours_ctx())
    solver.build_model()
    assert solver.solve(timeout_seconds=30) in ("OPTIMAL", "FEASIBLE")

    joint = {}
    for s in solver.extract_solution():
        if s.get("classe_accoppiata_id") and s["classe_id"] == "c1":
            joint[(s["docente_id"], s["giorno"])] = joint.get((s["docente_id"], s["giorno"]), 0) + 1
    assert joint, "la coppia deve avere ore in comune"
    assert max(joint.values()) == 1, f"un docente ha più ore in coppia nello stesso giorno: {joint}"
    assert not [c for c in solver.get_conflicts() if c["kind"] == "paired_hours_override"]


def test_paired_hours_cap_is_relaxed_only_with_a_visible_conflict():
    """Se solo un docente può coprire la coppia, il limite si rompe ma ogni rottura
    è un conflitto con la deroga suggerita (mai silenziosa)."""
    ass = [
        AssegnazioneDati("a1", "d1", "Prof Rossi", "ASSUNTO", "c1", "1A", "m1", "Pratica", "TEORIA", "ALTO", ore_residue=30),
        AssegnazioneDati("a2", "d1", "Prof Rossi", "ASSUNTO", "c2", "1B", "m1", "Pratica", "TEORIA", "ALTO", ore_residue=30),
    ]
    ctx = _minimal_context(
        assegnazioni=ass, classi_accoppiate=[("c1", "c2", "m1", "d1")], classi_set={"c1", "c2"},
    )
    solver = ScheduleSolver(ctx)
    solver.build_model()
    assert solver.solve(timeout_seconds=30) in ("OPTIMAL", "FEASIBLE")
    conflicts = [c for c in solver.get_conflicts() if c["kind"] == "paired_hours_override"]
    assert conflicts and all(c["suggested_action"]["action_type"] == "authorize_paired_hours" for c in conflicts)


def test_same_docente_avoids_consecutive_hours_on_the_same_pair():
    """Due docenti coprono la stessa coppia: le ore in comune si alternano, lo stesso
    docente non ha due ore di fila con la stessa coppia (finché c'è un'alternativa)."""
    solver = ScheduleSolver(_paired_hours_ctx())
    solver.build_model()
    assert solver.solve(timeout_seconds=30) in ("OPTIMAL", "FEASIBLE")

    joint = {}
    for s in solver.extract_solution():
        if s.get("classe_accoppiata_id") and s["classe_id"] == "c1":
            joint.setdefault((s["docente_id"], s["giorno"]), []).append(s["ora_inizio"])
    for (docente, giorno), ore in joint.items():
        ore.sort()
        assert all(b - a > 1 for a, b in zip(ore, ore[1:])), f"{docente} {giorno}: ore di fila {ore}"
    assert not [c for c in solver.get_conflicts() if c["kind"] == "paired_consecutive"]


def test_consecutive_pair_hours_are_reported_when_no_other_docente_exists():
    ass = [
        AssegnazioneDati("a1", "d1", "Prof Rossi", "ASSUNTO", "c1", "1A", "m1", "Pratica", "TEORIA", "ALTO", ore_residue=30),
        AssegnazioneDati("a2", "d1", "Prof Rossi", "ASSUNTO", "c2", "1B", "m1", "Pratica", "TEORIA", "ALTO", ore_residue=30),
    ]
    ctx = _minimal_context(assegnazioni=ass, classi_accoppiate=[("c1", "c2", "m1", "d1")], classi_set={"c1", "c2"})
    solver = ScheduleSolver(ctx)
    solver.build_model()
    assert solver.solve(timeout_seconds=30) in ("OPTIMAL", "FEASIBLE")
    assert [c for c in solver.get_conflicts() if c["kind"] == "paired_consecutive"]


def test_contractor_can_give_joint_lessons():
    """Un docente a contratto può fare lezioni in coppia: il conteggio dei buchi non deve
    contare due volte la stessa ora (lato A + lato B) e rendere il modello impossibile."""
    ass = [
        AssegnazioneDati("a1", "d1", "Prof Rossi", "CONTRATTO", "c1", "1A", "m1", "Pratica", "TEORIA", "ALTO", ore_residue=60),
        AssegnazioneDati("a2", "d1", "Prof Rossi", "CONTRATTO", "c2", "1B", "m1", "Pratica", "TEORIA", "ALTO", ore_residue=60),
        AssegnazioneDati("a3", "d2", "Prof Verdi", "ASSUNTO", "c1", "1A", "m2", "Altro", "TEORIA", "ALTO", ore_residue=240),
        AssegnazioneDati("a4", "d3", "Prof Neri", "ASSUNTO", "c2", "1B", "m2", "Altro", "TEORIA", "ALTO", ore_residue=240),
    ]
    ctx = _minimal_context(
        assegnazioni=ass, classi_accoppiate=[("c1", "c2", "m1", "d1")], classi_set={"c1", "c2"},
        docenti_map={"d1": "CONTRATTO", "d2": "ASSUNTO", "d3": "ASSUNTO"},
        materie_map={"m1": "TEORIA", "m2": "TEORIA"},
        disponibilita_map={"d1": DisponibilitaDati("d1", _full_availability())},
    )
    solver = ScheduleSolver(ctx)
    solver.build_model()
    assert solver.solve(timeout_seconds=30) in ("OPTIMAL", "FEASIBLE")
    assert [s for s in solver.extract_solution() if s["docente_id"] == "d1"], "il contratto deve poter fare le coppie"
