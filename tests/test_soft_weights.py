"""The feedback reasons, the solver's constraints and the tunable weights must stay in sync."""
from pathlib import Path

import pytest

from app.domain.soft_weights import (
    DEFAULT_SOFT_WEIGHTS,
    MAX_SOFT_WEIGHT,
    MOTIVO_CONSTRAINTS,
    resolve_soft_weights,
)
from app.services.feedback import MOTIVI
from tests.test_solver import _minimal_context
from app.domain.solver import ScheduleSolver

SOLVER_SRC = (Path(__file__).parent.parent / "app" / "domain" / "solver.py").read_text()


def test_every_reason_has_a_constraint_mapping_and_vice_versa():
    assert set(MOTIVI) == set(MOTIVO_CONSTRAINTS)


def test_mapped_kinds_exist_in_the_solver():
    """Guards against a kind being renamed in the solver (or typo'd here)."""
    for code, m in MOTIVO_CONSTRAINTS.items():
        for kind in m.kinds:
            assert f'kind="{kind}"' in SOLVER_SRC, f"{code}: solver has no kind {kind!r}"


def test_tunable_weights_line_up_with_the_mapping():
    tunables = {m.tunable for m in MOTIVO_CONSTRAINTS.values() if m.tunable}
    assert tunables == set(DEFAULT_SOFT_WEIGHTS)
    for code, m in MOTIVO_CONSTRAINTS.items():
        if m.tunable:
            assert m.tunable in m.kinds, f"{code}: tunable weight not among its own kinds"


def test_relaxable_hard_and_fixed_priority_reasons_are_not_tunable():
    for code in ("friday_late_start", "pratica_block", "classe_unfilled", "altro"):
        assert MOTIVO_CONSTRAINTS[code].tunable is None


def test_resolve_soft_weights():
    assert resolve_soft_weights() == DEFAULT_SOFT_WEIGHTS
    assert resolve_soft_weights({"contractor_gap": 30})["contractor_gap"] == 30
    assert DEFAULT_SOFT_WEIGHTS["contractor_gap"] != 30  # defaults untouched
    for bad in ({"nope": 5}, {"contractor_gap": 0}, {"contractor_gap": MAX_SOFT_WEIGHT + 1},
                {"contractor_gap": 1.5}, {"contractor_gap": True}):
        with pytest.raises(ValueError):
            resolve_soft_weights(bad)


def _weights_by_kind(solver):
    out = {}
    for p in solver.soft_penalties:
        out.setdefault(p.kind, set()).add(p.weight)
    return out


def test_solver_uses_default_weights_unless_overridden():
    base = ScheduleSolver(_minimal_context())
    base.build_model()
    by_kind = _weights_by_kind(base)
    # documented defaults (contractor_gap is spread over 6 hours: weight // 6)
    assert by_kind["teoria_consecutive"] == {DEFAULT_SOFT_WEIGHTS["teoria_consecutive"]}
    if "contractor_gap" in by_kind:
        assert by_kind["contractor_gap"] == {DEFAULT_SOFT_WEIGHTS["contractor_gap"] // 6}

    tuned = ScheduleSolver(_minimal_context(), soft_weights={"teoria_consecutive": 40})
    tuned.build_model()
    assert _weights_by_kind(tuned)["teoria_consecutive"] == {40}
    # the other constraints are unchanged
    for kind, w in by_kind.items():
        if kind != "teoria_consecutive":
            assert _weights_by_kind(tuned)[kind] == w


def test_solver_rejects_invalid_soft_weights():
    with pytest.raises(ValueError):
        ScheduleSolver(_minimal_context(), soft_weights={"classe_unfilled": 5})
