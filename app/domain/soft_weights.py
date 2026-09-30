"""
Which solver constraint each feedback reason (app.services.feedback.MOTIVI)
is about, and the weights of the soft constraints an admin's ratings could
tune.

Only the ordinary soft constraints have a tunable weight. The others are
deliberately fixed:
- "relaxable-hard" rules (Friday start at 8, pratica blocks of >= 3h) are
  enforced unless the admin grants a deroga, at RELAX_WEIGHT (1000) - the
  fix for a complaint about them is the deroga, not a weight.
- "classe_unfilled" (1500) sits above RELAX_WEIGHT on purpose: an empty
  classroom hour must never be traded for a soft preference.
"""
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# Default weight of each tunable soft constraint - the values the solver
# used before they became configurable, so behaviour is unchanged by default.
DEFAULT_SOFT_WEIGHTS: Dict[str, int] = {
    "classe_late_start": 100,
    "teoria_consecutive": 10,
    "ore_target_deviation": 15,
    "contractor_gap": 12,
    "single_classe_day": 10,
}

# Keeps every tunable soft constraint well under RELAX_WEIGHT (1000), so a
# preference can never outrank a rule that needs a deroga to be broken.
MAX_SOFT_WEIGHT = 200


@dataclass(frozen=True)
class MotivoConstraint:
    # SoftPenalty.kind values that show up as conflicts for this reason.
    kinds: Tuple[str, ...]
    # The key of DEFAULT_SOFT_WEIGHTS to raise when the reason is reported,
    # or None when the reason isn't fixable by a weight.
    tunable: Optional[str]
    why: str


MOTIVO_CONSTRAINTS: Dict[str, MotivoConstraint] = {
    "classe_late_start": MotivoConstraint(
        ("classe_late_start", "classe_early_start"), "classe_late_start",
        "Soft: a classe's day should start at 8:00.",
    ),
    "teoria_consecutive": MotivoConstraint(
        ("teoria_consecutive",), "teoria_consecutive",
        "Soft: no more than 2 consecutive hours of theory.",
    ),
    "contractor_gap": MotivoConstraint(
        ("contractor_gap",), "contractor_gap",
        "Soft: no gap hours for contractors (hours/days are paid).",
    ),
    "single_classe_day": MotivoConstraint(
        ("single_classe_day",), "single_classe_day",
        "Soft: discourages a docente's whole day on a single classe.",
    ),
    "ore_target_deviation": MotivoConstraint(
        ("ore_target_deviation", "monte_ore_exceeded"), "ore_target_deviation",
        "Soft: weekly hours close to the monte ore target.",
    ),
    "friday_late_start": MotivoConstraint(
        ("friday_late_start_override",), None,
        "Relaxable-hard: fix with authorize_friday_late_start, not a weight.",
    ),
    "pratica_block": MotivoConstraint(
        ("pratica_block_override",), None,
        "Relaxable-hard: fix with authorize_short_pratica_block, not a weight.",
    ),
    "classe_unfilled": MotivoConstraint(
        ("classe_unfilled", "classe_over_capacity"), None,
        "Fixed above RELAX_WEIGHT: an empty classroom hour is never traded for a preference.",
    ),
    "altro": MotivoConstraint((), None, "Free-text: needs a human to read the note."),
}


def resolve_soft_weights(overrides: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    """Defaults with `overrides` applied. Rejects unknown kinds and weights
    that aren't a positive int <= MAX_SOFT_WEIGHT."""
    weights = dict(DEFAULT_SOFT_WEIGHTS)
    for kind, value in (overrides or {}).items():
        if kind not in DEFAULT_SOFT_WEIGHTS:
            raise ValueError(f"Not a tunable soft constraint: {kind!r}")
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_SOFT_WEIGHT:
            raise ValueError(f"Weight for {kind!r} must be an int in 1..{MAX_SOFT_WEIGHT}, got {value!r}")
        weights[kind] = value
    return weights
