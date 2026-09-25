from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Tuple, Optional, Set
from enum import Enum
from ortools.sat.python import cp_model
import logging

logger = logging.getLogger(__name__)

GIORNI_NOMI_IT = {
    "LUNEDI": "Lunedì", "MARTEDI": "Martedì", "MERCOLEDI": "Mercoledì",
    "GIOVEDI": "Giovedì", "VENERDI": "Venerdì",
}


class GiornoEnum(Enum):
    """Day enum (0-4 for solver, mapped to LUNEDI-VENERDI)."""
    LUNEDI = 0
    MARTEDI = 1
    MERCOLEDI = 2
    GIOVEDI = 3
    VENERDI = 4


@dataclass
class AssegnazioneDati:
    """Teacher-Class-Subject assignment data."""
    assegnazione_id: str
    docente_id: str
    docente_nome: str
    docente_tipo: str  # "ASSUNTO" or "CONTRATTO"
    classe_id: str
    classe_nome: str
    materia_id: str
    materia_nome: str
    materia_tipo: str  # "TEORIA" or "PRATICA"
    peso_cognitivo: str  # "ALTO", "MEDIO", "BASSO"
    ore_residue: int  # ore_totali - ore_erogate


@dataclass
class DisponibilitaDati:
    """Teacher availability for week."""
    docente_id: str
    giorni_fasce: Dict  # {"lunedi": [...], ...}


@dataclass
class CalendarioDati:
    """
    Calendar day data for week.
    gruppo=None means this row applies school-wide (every classe); a
    non-None gruppo restricts it to classi whose gruppo matches (used for a
    calendar extracted from a per-year-group PDF, where daily hours differ
    by year group). Multiple rows can share the same (data, giorno) as long
    as their gruppo differs.
    """
    data: date
    giorno: int  # 0-4
    ore_max_giornata: int
    gruppo: Optional[str] = None
    flag_stage_classe_id: Optional[str] = None
    flag_stage_gruppo: bool = False  # whole gruppo on stage this giorno, see model docstring
    flag_chiusura: bool = False
    ora_inizio_min: Optional[int] = None  # 8-13: no lesson before this hour (staggered ingressi)


@dataclass
class ScheduleContext:
    """
    Immutable context for solver.
    All data pre-extracted from DB to decouple solver from SQLAlchemy.
    """
    scuola_id: str
    week_start: date
    week_end: date
    anno_fine: date  # end of the school's anno formativo (for weeks-remaining calc)

    # Core data
    assegnazioni: List[AssegnazioneDati]
    disponibilita_map: Dict[str, DisponibilitaDati]  # docente_id -> DisponibilitaDati
    calendario: List[CalendarioDati]  # 5 days of week
    classi_accoppiate: List[Tuple[str, str, str, Optional[str]]]  # (classe_a_id, classe_b_id, materia_id, docente_id)

    # Derived
    docenti_map: Dict[str, str]  # docente_id -> docente_tipo
    classi_set: Set[str]  # all classe_ids
    materie_map: Dict[str, str]  # materia_id -> materia_tipo
    classi_gruppo: Dict[str, Optional[str]] = None  # classe_id -> gruppo (year-group label)

    def __post_init__(self):
        if self.classi_gruppo is None:
            self.classi_gruppo = {}


@dataclass
class DerogaConfig:
    """
    A temporary, single-generation relaxation of one soft/hard constraint,
    triggered by an admin "quick action" in the UI (e.g. "Forza 3 ore
    teoria"). Scoped to one classe or docente when given; otherwise applies
    school-wide for this regeneration only (the relaxation is not persisted
    anywhere - the next plain regeneration goes back to normal rules).
    """
    action_type: str  # one of the QUICK_ACTIONS below
    classe_id: Optional[str] = None
    docente_id: Optional[str] = None


@dataclass
class SoftPenalty:
    """
    One soft-constraint violation instance the objective can penalize -
    carries enough context (beyond the raw IntVar/weight the objective
    needs) to describe it to an admin and, where one applies, point at the
    quick-action deroga that would relax it. See ScheduleSolver.get_conflicts.
    """
    var: Any  # cp_model IntVar; > 0 in the solution means this is violated
    weight: int
    kind: str  # "teoria_consecutive" | "ore_target_deviation" | "contractor_gap" | "classe_late_start" | "availability_override" | "single_classe_day" | "friday_late_start_override" | "pratica_block_override"
    description: str
    classe_id: Optional[str] = None
    docente_id: Optional[str] = None
    giorno: Optional[int] = None
    suggested_action: Optional[Dict[str, str]] = None
    # ore_target_deviation only: the assigned-hours vars + target, to work
    # out (after solving) whether this docente is over or under target -
    # only "over" for a CONTRATTO docente gets a suggested_action.
    hour_vars: Optional[List[Any]] = None
    # ore_target_deviation only: how the target was derived (residual hours,
    # weeks left, deroga), appended to the description once the actual
    # assigned hours are known.
    target_detail: Optional[str] = None
    ore_target: Optional[int] = None
    docente_tipo: Optional[str] = None


class ScheduleSolver:
    """
    Constraint Programming solver for school schedule generation.
    Uses Google OR-Tools CP-SAT solver.
    """

    def __init__(
        self,
        context: ScheduleContext,
        deroga: Optional[DerogaConfig] = None,
        exclude_docente_giorno: Optional[Set[Tuple[str, int]]] = None,
        max_hours_per_docente: Optional[Dict[str, int]] = None,
        max_consecutive_teoria: Optional[int] = None,
    ):
        """
        Initialize solver with problem context.

        The last three arguments exist for the AI chat's move/exclude/reduce
        requests (app/services/chat.py): unlike `deroga` (relaxes one rule),
        these *add* extra hard/soft restrictions for one regeneration -
        temporary and week-scoped, the same as a deroga, just tightening
        instead of loosening.
        - exclude_docente_giorno: {(docente_id, giorno_idx)} forced to 0
          hours that day (e.g. "escludi Prof Rossi martedì").
        - max_hours_per_docente: {docente_id: cap} hard weekly-hours cap
          (e.g. "riduci ore Prof Rossi a massimo 10").
        - max_consecutive_teoria: overrides the default 2-hour no-penalty
          cap for _soft_teoria_consecutive school-wide.
        """
        self.context = context
        self.deroga = deroga
        self.exclude_docente_giorno = exclude_docente_giorno or set()
        self.max_hours_per_docente = max_hours_per_docente or {}
        self.max_consecutive_teoria = max_consecutive_teoria
        self.model = None
        self.solver = None
        self.solution_callback = None
        self.status = None

        # Variables: x[assegnazione_id, giorno, ora] ∈ {0,1}
        self.x = {}

        # Soft constraint penalties
        self.soft_penalties = []

        # (classe_id, giorno) -> [(ora, start_var), ...] from
        # _constraint_no_classe_schedule_gaps, reused by
        # _soft_classe_start_at_8 so "which hour starts the day's one
        # lesson block" is only modeled once.
        self._classe_day_starts: Dict[Tuple[str, int], List[Tuple[int, Any]]] = {}

    def build_model(self) -> "ScheduleSolver":
        """
        Build OR-Tools CP-SAT model.
        Creates variables and adds hard/soft constraints.
        """
        logger.info(f"Building model for school {self.context.scuola_id} week {self.context.week_start}")

        self.model = cp_model.CpModel()

        # 1. Create decision variables
        self._create_variables()

        # 2. Add hard constraints
        self._add_hard_constraints()

        # 3. Add soft constraints
        self._add_soft_constraints()

        # 4. Set objective function (weighted sum: `weight` was previously
        # computed per soft constraint but silently dropped here, so every
        # soft violation cost the same regardless of its intended priority)
        if self.soft_penalties:
            self.model.Minimize(sum(p.var * p.weight for p in self.soft_penalties))

        logger.info(f"Model built: {len(self.x)} variables, {len(self.model.Proto().constraints)} constraints")
        return self

    def _create_variables(self) -> None:
        """Create decision variables: x[assegnazione_id, giorno, ora]."""
        for asg in self.context.assegnazioni:
            for giorno in range(5):  # 0-4 (LUN-VEN)
                for ora in range(6):  # 0-5 (08:00-14:00)
                    var_name = f"x_{asg.assegnazione_id}_{giorno}_{ora}"
                    self.x[(asg.assegnazione_id, giorno, ora)] = self.model.NewBoolVar(var_name)

    def _add_hard_constraints(self) -> None:
        """Add hard constraints (non-violable)."""
        logger.info("Adding hard constraints...")

        # Hard 1: No teacher double-booking
        self._constraint_no_double_booking()

        # Hard 1b: A classe can only have one lesson at a time
        self._constraint_classe_no_overlap()

        # Hard 2: Day capacity constraint
        self._constraint_day_capacity()

        # Hard 2b: No gaps in a classe's daily schedule
        self._constraint_no_classe_schedule_gaps()

        # Hard 2c: Staggered ingressi (per-classe earliest start hour)
        self._constraint_classe_start_time()

        # Hard 2d: Friday must start at 8:00 (relaxable at an extreme
        # weight, see _constraint_friday_start_at_8's docstring)
        self._constraint_friday_start_at_8()

        # Hard 2e: PRATICA hours must form one >=3h contiguous block, or
        # none at all (relaxable at an extreme weight, see
        # _constraint_pratica_block_min_3h's docstring)
        self._constraint_pratica_block_min_3h()

        # Hard 3: Paired classes
        self._constraint_paired_classes()

        # Hard 4: Teacher availability (relaxable at an extreme weight, see
        # _constraint_teacher_availability's docstring)
        self._constraint_teacher_availability()

        # Hard 5: Exclude stage classes
        self._constraint_exclude_stage()

        # Hard 6: Don't exceed residual hours
        self._constraint_monte_ore_limit()

        # Hard 7 & 8: AI-chat-requested exclusions/caps for this run (see __init__)
        self._constraint_chat_exclusions()
        self._constraint_chat_max_hours()

    def _deroga_active(self, action_type: str, *, classe_id: str = None, docente_id: str = None) -> bool:
        """
        True if `self.deroga` requests relaxing `action_type` and, when the
        deroga is scoped to a classe/docente, the given one matches (an
        unscoped deroga applies to everyone).
        """
        if not self.deroga or self.deroga.action_type != action_type:
            return False
        if self.deroga.classe_id and classe_id and self.deroga.classe_id != classe_id:
            return False
        if self.deroga.docente_id and docente_id and self.deroga.docente_id != docente_id:
            return False
        return True

    def _paired_assignment_pair(
        self, classe_a: str, classe_b: str, materia_id: str, docente_id: Optional[str]
    ) -> Optional[Tuple["AssegnazioneDati", "AssegnazioneDati"]]:
        """
        A classe-accoppiata row names the SPECIFIC docente who actually runs
        the joint lesson for that pair (see ClasseAccoppiata's docstring) -
        this finds that one docente's own assegnazione on each side. Returns
        None if the row has no docente_id (a legacy/manually-created row
        without one isn't enforced - we don't know who the joint teacher
        is) or that docente doesn't actually have an assegnazione on both
        sides.
        """
        if not docente_id:
            return None
        asg_a = next((a for a in self.context.assegnazioni if a.classe_id == classe_a
                      and a.materia_id == materia_id and a.docente_id == docente_id), None)
        asg_b = next((a for a in self.context.assegnazioni if a.classe_id == classe_b
                      and a.materia_id == materia_id and a.docente_id == docente_id), None)
        return (asg_a, asg_b) if asg_a and asg_b else None

    def _paired_assignment_ids_to_dedupe(self) -> Set[str]:
        """
        _constraint_paired_classes forces the shared docente's two
        assegnazioni (one per side of the pair) to always be equal
        (x_a == x_b): together they represent a single joint lesson, not two
        separate bookings. Without this, _constraint_no_double_booking would
        sum both into the same docente/giorno/ora slot and force the pair to
        always be 0 (sum <= 1 vs. x_a == x_b == 1 is unsatisfiable). Returns
        the assegnazione_ids of the "B" side of every such pair, to be
        excluded from that sum.
        """
        skip_ids: Set[str] = set()
        for classe_a, classe_b, materia_id, docente_id in self.context.classi_accoppiate:
            pair = self._paired_assignment_pair(classe_a, classe_b, materia_id, docente_id)
            if pair:
                skip_ids.add(pair[1].assegnazione_id)
        return skip_ids

    def _constraint_no_double_booking(self) -> None:
        """Hard constraint 1: No teacher can teach 2 classes in same hour."""
        skip_ids = self._paired_assignment_ids_to_dedupe()

        # Group assegnazioni by docente
        docenti_asgs = {}
        for asg in self.context.assegnazioni:
            if asg.docente_id not in docenti_asgs:
                docenti_asgs[asg.docente_id] = []
            docenti_asgs[asg.docente_id].append(asg)

        # For each docente/giorno/ora, max 1 slot
        for docente_id, asgs in docenti_asgs.items():
            for giorno in range(5):
                for ora in range(6):
                    overlapping = [
                        self.x[(asg.assegnazione_id, giorno, ora)]
                        for asg in asgs
                        if asg.assegnazione_id not in skip_ids
                        and (asg.assegnazione_id, giorno, ora) in self.x
                    ]
                    if overlapping:
                        self.model.Add(sum(overlapping) <= 1)

    def _constraint_classe_no_overlap(self) -> None:
        """
        Hard constraint 1b: a classe can only be in one lesson at a time -
        at most one assegnazione (any docente) active per classe/giorno/ora.

        _constraint_day_capacity only bounds the day's *total* filled-hour
        count (now pinned exactly to ore_max_giornata), not which specific
        hours those are - without this, nothing would stop several docenti
        being piled onto the same hour (which still counts toward that
        total) while other hours of the day stayed empty.
        """
        classi_asgs: Dict[str, List[AssegnazioneDati]] = {}
        for asg in self.context.assegnazioni:
            classi_asgs.setdefault(asg.classe_id, []).append(asg)

        for classe_id, asgs in classi_asgs.items():
            for giorno in range(5):
                for ora in range(6):
                    overlapping = [
                        self.x[(asg.assegnazione_id, giorno, ora)]
                        for asg in asgs
                        if (asg.assegnazione_id, giorno, ora) in self.x
                    ]
                    if overlapping:
                        self.model.Add(sum(overlapping) <= 1)

    def _ore_max_for_classe_giorno(self, classe_id: str, giorno: int) -> int:
        """
        Resolve the daily hour cap for a classe on a given giorno.
        Looks for a calendar row scoped to this classe's gruppo first (a
        per-year-group PDF calendar), then falls back to a school-wide row
        (gruppo=None, e.g. a plain CSV calendar or an inferred closure), then
        to a hardcoded default if neither exists.
        """
        # A classe in stage that day has 0 lesson hours regardless of what
        # the calendar's normal ore_max_giornata says - _constraint_day_capacity
        # now requires an exact match (not just <=), so this has to agree with
        # _constraint_exclude_stage or the two would be jointly infeasible.
        for c in self.context.calendario:
            if c.giorno == giorno and c.flag_stage_classe_id == classe_id:
                return 0

        gruppo = self.context.classi_gruppo.get(classe_id)

        if gruppo is not None:
            for c in self.context.calendario:
                if c.giorno == giorno and c.gruppo == gruppo and c.flag_stage_gruppo:
                    return 0

        if gruppo is not None:
            for c in self.context.calendario:
                if c.giorno == giorno and c.gruppo == gruppo:
                    return 0 if c.flag_chiusura else c.ore_max_giornata

        for c in self.context.calendario:
            if c.giorno == giorno and c.gruppo is None:
                return 0 if c.flag_chiusura else c.ore_max_giornata

        return 6  # no calendar data at all for this day: default

    def _ora_inizio_min_for_classe_giorno(self, classe_id: str, giorno: int) -> Optional[int]:
        """
        Resolve the earliest allowed lesson hour (8-13) for a classe on a
        given giorno, e.g. to stagger ingressi across gruppi so not every
        classe starts at 8:00. None means no minimum (may start at 8:00).
        Same gruppo-then-school-wide lookup order as _ore_max_for_classe_giorno.
        """
        gruppo = self.context.classi_gruppo.get(classe_id)

        if gruppo is not None:
            for c in self.context.calendario:
                if c.giorno == giorno and c.gruppo == gruppo and c.ora_inizio_min is not None:
                    return c.ora_inizio_min

        for c in self.context.calendario:
            if c.giorno == giorno and c.gruppo is None and c.ora_inizio_min is not None:
                return c.ora_inizio_min

        return None

    def _constraint_classe_start_time(self) -> None:
        """
        Hard constraint 2c: a classe can't have a lesson before its
        resolved ora_inizio_min this giorno (see
        _ora_inizio_min_for_classe_giorno) - lets an admin stagger ingressi
        across gruppi instead of every classe defaulting to 8:00, the only
        hour with nothing pushing lessons away from it.
        """
        classi_asgs: Dict[str, List[AssegnazioneDati]] = {}
        for asg in self.context.assegnazioni:
            classi_asgs.setdefault(asg.classe_id, []).append(asg)

        for classe_id, asgs in classi_asgs.items():
            for giorno in range(5):
                ora_min = self._ora_inizio_min_for_classe_giorno(classe_id, giorno)
                if not ora_min:
                    continue
                for asg in asgs:
                    for ora in range(min(ora_min - 8, 6)):
                        key = (asg.assegnazione_id, giorno, ora)
                        if key in self.x:
                            self.model.Add(self.x[key] == 0)

    def _constraint_friday_start_at_8(self) -> None:
        """
        Hard constraint 2d, but relaxable: a classe's Friday lesson block
        MUST start at 8:00 - admin decision (2026-09-23), stronger than the
        top-tier soft preference _soft_classe_start_at_8 already gives
        every day (weight 100): for Friday specifically this is enforced
        as (near-)hard, not a tie-break the solver can trade away.

        Modeled with the same relaxable-hard pattern as
        _constraint_teacher_availability: an "override" bool var at
        RELAX_WEIGHT (1000, an order of magnitude above every ordinary soft
        weight, including _soft_classe_start_at_8's own 100) lets the
        solver only break it when truly no other combination works that
        Friday. Always surfaced via get_conflicts() with an
        "authorize_friday_late_start" suggested_action - never a silent
        late start, an admin has to explicitly grant permission (the same
        deroga/quick-action mechanism as override_availability etc.).

        Skips a classe/giorno with no Friday lesson at all (closure/stage,
        ore_max_giornata == 0 - nothing to force) or where an explicit
        ora_inizio_min staggers that classe's Friday ingresso past 8:00 on
        purpose (_constraint_classe_start_time already forces that; forcing
        8:00 here too would just always be infeasible/always-relaxed noise).
        """
        RELAX_WEIGHT = 1000
        venerdi = GiornoEnum.VENERDI.value
        classe_nomi = {asg.classe_id: asg.classe_nome for asg in self.context.assegnazioni}

        for (classe_id, giorno), starts_by_ora in self._classe_day_starts.items():
            if giorno != venerdi:
                continue
            if self._ore_max_for_classe_giorno(classe_id, giorno) <= 0:
                continue
            ora_min = self._ora_inizio_min_for_classe_giorno(classe_id, giorno)
            if ora_min and ora_min > 8:
                continue
            if len(starts_by_ora) < 2 or starts_by_ora[0][0] != 0:
                continue  # no 8:00 slot to require for this classe/giorno

            if self._deroga_active("authorize_friday_late_start", classe_id=classe_id):
                continue

            start_at_8 = starts_by_ora[0][1]
            relax = self.model.NewBoolVar(f"friday_late_start_override_{classe_id}")
            self.model.Add(start_at_8 == 1).OnlyEnforceIf(relax.Not())
            self.soft_penalties.append(SoftPenalty(
                var=relax, weight=RELAX_WEIGHT, kind="friday_late_start_override",
                description=(
                    f"Inizio venerdì forzato dopo le 8:00 per {classe_nomi.get(classe_id, classe_id)}: "
                    "nessun'altra combinazione permetteva di iniziare alle 8:00"
                ),
                classe_id=classe_id, giorno=giorno,
                suggested_action={
                    "action_type": "authorize_friday_late_start",
                    "label": "Autorizza inizio posticipato di venerdì",
                },
            ))

    def _constraint_day_capacity(self) -> None:
        """Hard constraint 2: a class's daily hours must equal
        ore_max_giornata exactly - no free/"Libera" hours, by admin
        decision (2026-09-18): every classroom hour must be filled, even at
        the cost of the whole week failing to generate (INFEASIBLE) when
        the docenti actually available that day can't cover it. This
        replaced an earlier <= formulation with a soft fill-rate goal
        (_soft_no_free_hours, since removed) that tolerated gaps the way
        the real historical example timetable had them (Documenti/
        es_di_calendario.pdf was only ~96% full) - the admin wants gaps
        surfaced as a generation failure to fix (docenti/disponibilita),
        not silently accepted in the output."""
        # Group assegnazioni by classe
        classi_asgs = {}
        for asg in self.context.assegnazioni:
            if asg.classe_id not in classi_asgs:
                classi_asgs[asg.classe_id] = []
            classi_asgs[asg.classe_id].append(asg)

        # For each classe/giorno
        for classe_id, asgs in classi_asgs.items():
            for giorno in range(5):
                ore_max = self._ore_max_for_classe_giorno(classe_id, giorno)

                # Sum all hours for this classe/giorno
                hours_in_day = [
                    self.x[(asg.assegnazione_id, giorno, ora)]
                    for asg in asgs
                    for ora in range(6)
                    if (asg.assegnazione_id, giorno, ora) in self.x
                ]

                if hours_in_day:
                    self.model.Add(sum(hours_in_day) == ore_max)

    def _constraint_no_classe_schedule_gaps(self) -> None:
        """
        Hard constraint 2b: a classe's lesson hours in a day must form one
        contiguous block - no "ora buca" (a free hour with lessons both
        before and after it). Now that _constraint_day_capacity pins the
        day's total to exactly ore_max_giornata, this only has teeth on a
        shorter day (e.g. Friday's 5-hour cap leaves one of the 6 slots
        free): it forces that one free slot to sit at the start or end of
        the day, never in the middle.

        Encoded as: at most one "run" of occupied hours per classe/giorno,
        where an hour starts a run iff it's occupied and the previous hour
        wasn't - two or more runs means at least one gap sits between them.
        """
        classi_asgs: Dict[str, List[AssegnazioneDati]] = {}
        for asg in self.context.assegnazioni:
            classi_asgs.setdefault(asg.classe_id, []).append(asg)

        for classe_id, asgs in classi_asgs.items():
            for giorno in range(5):
                occupied: List[Any] = []
                for ora in range(6):
                    slots = [
                        self.x[(asg.assegnazione_id, giorno, ora)]
                        for asg in asgs
                        if (asg.assegnazione_id, giorno, ora) in self.x
                    ]
                    if not slots:
                        occupied.append(None)
                        continue
                    # _constraint_classe_no_overlap already caps this sum at
                    # 1, so it doubles as a 0/1 "is this hour occupied" var.
                    occ = self.model.NewBoolVar(f"occ_{classe_id}_{giorno}_{ora}")
                    self.model.Add(sum(slots) == occ)
                    occupied.append(occ)

                starts = []
                starts_by_ora = []
                prev = None
                for i, occ in enumerate(occupied):
                    if occ is None:
                        prev = None
                        continue
                    start = self.model.NewBoolVar(f"start_{classe_id}_{giorno}_{i}")
                    if prev is None:
                        self.model.Add(start == occ)
                    else:
                        self.model.Add(start <= occ)
                        self.model.Add(start <= 1 - prev)
                        self.model.Add(start >= occ - prev)
                    starts.append(start)
                    starts_by_ora.append((i, start))
                    prev = occ

                if starts:
                    self.model.Add(sum(starts) <= 1)
                self._classe_day_starts[(classe_id, giorno)] = starts_by_ora

    def _constraint_paired_classes(self) -> None:
        """
        Hard constraint 3: for a classe-accoppiata, only its named docente
        (the one who actually teaches BOTH sides, see ClasseAccoppiata's
        docstring) must have matching giorno/ora (one joint lesson). Every
        other docente of either class is unaffected - most of a paired
        class's day is still independent, normal lessons with its *other*
        docenti; see _paired_assignment_pair.
        """
        for classe_a, classe_b, materia_id, docente_id in self.context.classi_accoppiate:
            pair = self._paired_assignment_pair(classe_a, classe_b, materia_id, docente_id)
            if not pair:
                continue
            asg_a, asg_b = pair
            for giorno in range(5):
                for ora in range(6):
                    key_a = (asg_a.assegnazione_id, giorno, ora)
                    key_b = (asg_b.assegnazione_id, giorno, ora)

                    if key_a in self.x and key_b in self.x:
                        self.model.Add(self.x[key_a] == self.x[key_b])

    def _constraint_teacher_availability(self) -> None:
        """
        Hard constraint 4, but relaxable: respect teacher availability +
        ASSUNTO's implicit 8-14 range.

        Not fully hard, though: _constraint_day_capacity now demands 100%
        classroom fill every day, and a CONTRATTO docente's recorded day
        off is exactly the kind of thing that can make a week impossible
        to fill even though it's otherwise entirely solvable. So instead
        of an unconditional block, each (docente, giorno) that would
        otherwise force 0 hours gets its own "override" bool var, at an
        extreme weight (1000 - two orders of magnitude above every other
        soft goal, see RELAX_WEIGHT) so the solver only breaks a docente's
        day off when there is truly no other way to reach full fill, and
        does so on the fewest (docente, giorno) pairs possible. Surfaced
        via get_conflicts() with an "override_availability"
        suggested_action - the same deroga an admin would apply by hand -
        so a forced override is always visible and actionable, never a
        silent change to the docente's recorded disponibilita.
        """
        RELAX_WEIGHT = 1000
        giorni_nomi = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi"]

        asgs_by_docente: Dict[str, List[AssegnazioneDati]] = {}
        for asg in self.context.assegnazioni:
            asgs_by_docente.setdefault(asg.docente_id, []).append(asg)

        for docente_id, asgs in asgs_by_docente.items():
            docente_tipo = self.context.docenti_map.get(docente_id)

            # ASSUNTO: implicit (already limited to 0-5 which is 8-14)
            if docente_tipo == "ASSUNTO":
                continue

            # Deroga: "Deroga disponibilità" - admin override, skip enforcing
            # the recorded availability for this docente this run.
            if self._deroga_active("override_availability", docente_id=docente_id):
                continue

            disponibilita = self.context.disponibilita_map.get(docente_id)
            docente_nome = asgs[0].docente_nome

            for giorno in range(5):
                if disponibilita:
                    giorno_nome = giorni_nomi[giorno]
                    unavailable_ore: List[int] = []
                    for slot in disponibilita.giorni_fasce.get(giorno_nome, []):
                        if slot.get("disponibile", False):
                            continue
                        try:
                            hora_idx = int(slot["ora_inizio"].split(":")[0]) - 8  # 8->0, ..., 13->5
                        except (ValueError, KeyError):
                            logger.warning(f"Invalid time slot format: {slot}")
                            continue
                        if 0 <= hora_idx < 6:
                            unavailable_ore.append(hora_idx)
                else:
                    # No availability recorded -> treat as unavailable all week
                    logger.warning(f"No availability found for CONTRATTO {docente_id}, treating as unavailable")
                    unavailable_ore = list(range(6))

                if not unavailable_ore:
                    continue

                relax = self.model.NewBoolVar(f"avail_override_{docente_id}_{giorno}")
                for asg in asgs:
                    for hora_idx in unavailable_ore:
                        key = (asg.assegnazione_id, giorno, hora_idx)
                        if key in self.x:
                            self.model.Add(self.x[key] == 0).OnlyEnforceIf(relax.Not())

                self.soft_penalties.append(SoftPenalty(
                    var=relax, weight=RELAX_WEIGHT, kind="availability_override",
                    description=(
                        f"Disponibilità forzata per {docente_nome} "
                        f"({GIORNI_NOMI_IT[GiornoEnum(giorno).name]}): nessun'altra "
                        "combinazione riempiva tutte le ore delle classi"
                    ),
                    docente_id=docente_id, giorno=giorno,
                    suggested_action={
                        "action_type": "override_availability",
                        "label": "Conferma disponibilità forzata",
                    },
                ))

    def _constraint_exclude_stage(self) -> None:
        """Hard constraint 5: Exclude classes in stage from scheduling."""
        for giorno_data in self.context.calendario:
            giorno = giorno_data.giorno

            if giorno_data.flag_stage_classe_id:
                classi_in_stage = [giorno_data.flag_stage_classe_id]
            elif giorno_data.flag_stage_gruppo and giorno_data.gruppo:
                classi_in_stage = [
                    classe_id for classe_id, gruppo in self.context.classi_gruppo.items()
                    if gruppo == giorno_data.gruppo
                ]
            else:
                continue

            asgs_in_stage = [
                asg for asg in self.context.assegnazioni
                if asg.classe_id in classi_in_stage
            ]

            # Zero out all slots for these classi on this giorno
            for asg in asgs_in_stage:
                for ora in range(6):
                    key = (asg.assegnazione_id, giorno, ora)
                    if key in self.x:
                        self.model.Add(self.x[key] == 0)

    def _constraint_monte_ore_limit(self) -> None:
        """Hard constraint 6: Don't exceed residual hours for assegnazione."""
        for asg in self.context.assegnazioni:
            if asg.ore_residue <= 0:
                # No hours left -> can't assign
                for giorno in range(5):
                    for ora in range(6):
                        key = (asg.assegnazione_id, giorno, ora)
                        if key in self.x:
                            self.model.Add(self.x[key] == 0)
            else:
                # Sum of all slots <= ore_residue
                slots_for_asg = [
                    self.x[(asg.assegnazione_id, giorno, ora)]
                    for giorno in range(5)
                    for ora in range(6)
                    if (asg.assegnazione_id, giorno, ora) in self.x
                ]
                if slots_for_asg:
                    self.model.Add(sum(slots_for_asg) <= asg.ore_residue)

    def _constraint_chat_exclusions(self) -> None:
        """Hard constraint 7: zero out a docente's hours on a specific giorno (chat "escludi ... giorno")."""
        if not self.exclude_docente_giorno:
            return
        for asg in self.context.assegnazioni:
            for giorno in range(5):
                if (asg.docente_id, giorno) not in self.exclude_docente_giorno:
                    continue
                for ora in range(6):
                    key = (asg.assegnazione_id, giorno, ora)
                    if key in self.x:
                        self.model.Add(self.x[key] == 0)

    def _constraint_chat_max_hours(self) -> None:
        """Hard constraint 8: cap a docente's total weekly hours (chat "riduci ore ... massimo N")."""
        if not self.max_hours_per_docente:
            return
        for docente_id, cap in self.max_hours_per_docente.items():
            slots_for_docente = [
                self.x[(asg.assegnazione_id, giorno, ora)]
                for asg in self.context.assegnazioni
                if asg.docente_id == docente_id
                for giorno in range(5)
                for ora in range(6)
                if (asg.assegnazione_id, giorno, ora) in self.x
            ]
            if slots_for_docente:
                self.model.Add(sum(slots_for_docente) <= cap)

    def _add_soft_constraints(self) -> None:
        """Add soft constraints (optimizable)."""
        logger.info("Adding soft constraints...")

        # Soft 1: Max 2 ore teoria consecutive (weight 10)
        self._soft_teoria_consecutive()

        # Soft 3: Minimize deviation from ore_target per assegnazione (weight 15)
        self._soft_ore_target_deviation()

        # Soft 4: Minimize ore buche for contrattisti (weight 12)
        self._soft_contractor_gaps()

        # Soft 4b: Avoid a docente spending a whole day with one classe
        # (weight 10)
        self._soft_avoid_single_classe_day()

        # Soft 5: Start the day at 8:00 (weight 100 - top priority; only
        # yield to a later start when 8:00 is genuinely unavailable that
        # day, see _soft_classe_start_at_8). Filling every classroom hour
        # is now a HARD constraint (_constraint_day_capacity), not a soft
        # goal - there's no more "free hours" to minimize here.
        self._soft_classe_start_at_8()

    def _soft_classe_start_at_8(self) -> None:
        """
        Soft: a classe should start its day at 8:00 whenever possible -
        weighted at the top tier (100) so the solver only pushes a classe's
        start later than 8:00 when nothing else can make 8:00 work that day
        (e.g. its docente isn't available then), not as an arbitrary
        tie-break. On a full ore_max_giornata day this is moot -
        _constraint_day_capacity + _constraint_no_classe_schedule_gaps
        already force one contiguous block spanning the whole day - it only
        matters on a shorter day (e.g. Friday), where 8:00-13:00 and
        9:00-14:00 both satisfy those hard constraints equally well. Not a
        hard constraint itself: an explicit ora_inizio_min override (see
        _constraint_classe_start_time) still needs to be able to ask for a
        later start on purpose.

        Reuses the per-(classe, giorno) "which hour starts the day's one
        lesson block" vars built in _constraint_no_classe_schedule_gaps:
        exactly one of them is 1 when the classe has any lesson that day
        (none if the day is entirely free), so summing every start var
        *except* hour 0's gives a 0/1 "didn't start at 8:00" penalty.
        """
        weight = 100
        classe_nomi = {asg.classe_id: asg.classe_nome for asg in self.context.assegnazioni}

        for (classe_id, giorno), starts_by_ora in self._classe_day_starts.items():
            if len(starts_by_ora) < 2 or starts_by_ora[0][0] != 0:
                continue  # no 8:00 slot for this classe/giorno to prefer

            late_starts = [start for ora, start in starts_by_ora if ora != 0]
            late_start = self.model.NewBoolVar(f"late_start_{classe_id}_{giorno}")
            self.model.Add(late_start == sum(late_starts))
            self.soft_penalties.append(SoftPenalty(
                var=late_start, weight=weight, kind="classe_late_start",
                description=(
                    f"Inizio dopo le 8:00 per {classe_nomi.get(classe_id, classe_id)} "
                    f"({GIORNI_NOMI_IT[GiornoEnum(giorno).name]})"
                ),
            ))

    def _soft_teoria_consecutive(self) -> None:
        """
        Soft: max 2 consecutive theory hours from the SAME docente.

        Scoped per (classe, docente) rather than per classe: with every
        assegnazione currently sharing one placeholder Materia (real subject
        data isn't in yet), grouping by classe alone summed every docente's
        hours into the same window and effectively forbade filling more than
        ~2 hours of any of a class's day at all, docente changes included -
        a teacher handoff is its own natural break, the same as a subject
        change would be, so it shouldn't count toward the same run.
        """
        weight = 10

        teoria_asgs = [asg for asg in self.context.assegnazioni if asg.materia_tipo == "TEORIA"]

        by_classe_docente: Dict[Tuple[str, str], List[AssegnazioneDati]] = {}
        for asg in teoria_asgs:
            by_classe_docente.setdefault((asg.classe_id, asg.docente_id), []).append(asg)

        for (classe_id, docente_id), asgs in by_classe_docente.items():
            classe_nome = asgs[0].classe_nome
            docente_nome = asgs[0].docente_nome

            # Base cap: 2, unless the chat asked for a specific value
            # ("imposta massimo 3 ore consecutive di teoria").
            max_consecutive = self.max_consecutive_teoria if self.max_consecutive_teoria is not None else 2

            # Deroga: "Forza 3 ore teoria" - raise the no-penalty cap to 3
            # consecutive hours for this classe (or every classe, if the
            # deroga isn't scoped to one).
            if self._deroga_active("force_3_hours_theory", classe_id=classe_id):
                max_consecutive = 3

            for giorno in range(5):
                # Check 3-hour windows (e.g., ora 0-1-2, 1-2-3, etc.)
                for ora_start in range(4):  # 0-3 (can check up to 5-6)
                    # Sum hours in window: ora_start, ora_start+1, ora_start+2
                    hours_in_window = [
                        self.x[(asg.assegnazione_id, giorno, ora_start + h)]
                        for asg in asgs
                        for h in range(3)
                        if (asg.assegnazione_id, giorno, ora_start + h) in self.x
                    ]

                    if hours_in_window:
                        # Penalize if hours in window exceed the cap
                        excess = self.model.NewIntVar(
                            0, 3, f"excess_teoria_{classe_id}_{docente_id}_{giorno}_{ora_start}"
                        )
                        self.model.Add(excess >= sum(hours_in_window) - max_consecutive)
                        self.soft_penalties.append(SoftPenalty(
                            var=excess, weight=weight, kind="teoria_consecutive",
                            description=(
                                f"Troppe ore consecutive di {docente_nome} su {classe_nome} "
                                f"({GIORNI_NOMI_IT[GiornoEnum(giorno).name]})"
                            ),
                            classe_id=classe_id, docente_id=docente_id, giorno=giorno,
                            suggested_action={"action_type": "force_3_hours_theory", "label": "Forza 3 ore teoria"},
                        ))

    def _constraint_pratica_block_min_3h(self) -> None:
        """
        Hard constraint 2e, but relaxable: PRATICA/laboratorio hours must
        form one contiguous block of at least min(3, day_cap) hours per day
        per assegnazione, or none at all that day - admin decision
        (2026-09-23): "almeno 3 ore di laboratorio di fila, oppure nulla",
        top priority. Promotes the two penalties the old weight-8
        `_soft_pratica_blocks` used to just discourage (specs.md 4.1:
        "blocchi da 3 a 6 ore, adattati alla capienza massima del giorno se
        la giornata è corta") into a near-hard requirement, same
        relaxable-hard pattern as _constraint_friday_start_at_8 /
        _constraint_teacher_availability: one override bool var per
        (assegnazione, giorno) at RELAX_WEIGHT (1000, an order of magnitude
        above every ordinary soft weight) lets the solver break it only
        when truly unavoidable, surfaced via get_conflicts() with an
        "authorize_short_pratica_block" suggested_action/deroga - an admin
        must explicitly grant permission, never a silent short/scattered
        block.

        Two complementary conditions approximate "one contiguous block in
        [3,6]" without a full interval-scheduling formulation (same idiom
        as before, now both gated by the same override var):
        1. the day's total hours for this assegnazione, if any are
           scheduled that day at all, must not fall below min(3, day_cap) -
           day_cap adapts the target down on a short day. There's no
           symmetric "too long" check: this assegnazione's hours that day
           are already a subset of the classe's daily total, which
           _constraint_day_capacity hard-caps at day_cap (<=6, the whole
           08:00-14:00 window), so a block exceeding 6h can't occur in the
           first place;
        2. no "hole": an hour with practice both immediately before and
           after it but not itself scheduled - same gap-detection idiom as
           _soft_contractor_gaps - forbids scattering the day's hours into
           disconnected pieces even when the total is already within range.
        """
        RELAX_WEIGHT = 1000

        pratica_asgs = [asg for asg in self.context.assegnazioni if asg.materia_tipo == "PRATICA"]

        for asg in pratica_asgs:
            for giorno in range(5):
                hours = [
                    self.x[(asg.assegnazione_id, giorno, ora)]
                    for ora in range(6)
                    if (asg.assegnazione_id, giorno, ora) in self.x
                ]
                if not hours:
                    continue

                if self._deroga_active("authorize_short_pratica_block", classe_id=asg.classe_id):
                    continue

                day_cap = self._ore_max_for_classe_giorno(asg.classe_id, giorno)
                low = min(3, day_cap)
                ore_in_day = sum(hours)
                giorno_nome = GIORNI_NOMI_IT[GiornoEnum(giorno).name]

                relax = self.model.NewBoolVar(f"pratica_block_override_{asg.assegnazione_id}_{giorno}")

                # Too-short block, only counted on a day this assegnazione
                # actually has practice hours at all (a day with none
                # isn't "a block", so it isn't penalized).
                used = self.model.NewBoolVar(f"pratica_used_{asg.assegnazione_id}_{giorno}")
                self.model.Add(ore_in_day >= 1).OnlyEnforceIf(used)
                self.model.Add(ore_in_day == 0).OnlyEnforceIf(used.Not())

                too_short = self.model.NewIntVar(0, 6, f"pratica_short_{asg.assegnazione_id}_{giorno}")
                self.model.Add(too_short >= low - ore_in_day).OnlyEnforceIf(used)
                self.model.Add(too_short == 0).OnlyEnforceIf(used.Not())
                self.model.Add(too_short == 0).OnlyEnforceIf(relax.Not())

                # Holes inside an otherwise-active span.
                for ora in range(1, 5):
                    before = (asg.assegnazione_id, giorno, ora - 1)
                    here = (asg.assegnazione_id, giorno, ora)
                    after = (asg.assegnazione_id, giorno, ora + 1)
                    if before in self.x and here in self.x and after in self.x:
                        hole = self.model.NewIntVar(0, 1, f"pratica_hole_{asg.assegnazione_id}_{giorno}_{ora}")
                        self.model.Add(hole >= self.x[before] + self.x[after] - 1 - self.x[here])
                        self.model.Add(hole == 0).OnlyEnforceIf(relax.Not())

                self.soft_penalties.append(SoftPenalty(
                    var=relax, weight=RELAX_WEIGHT, kind="pratica_block_override",
                    description=(
                        f"Blocco pratica corto/non contiguo per {asg.classe_nome}/{asg.materia_nome} "
                        f"({giorno_nome}): nessun'altra combinazione permetteva un blocco di almeno "
                        f"{low}h consecutive"
                    ),
                    classe_id=asg.classe_id, giorno=giorno,
                    suggested_action={
                        "action_type": "authorize_short_pratica_block",
                        "label": "Autorizza blocco pratica corto",
                    },
                ))

    def _soft_ore_target_deviation(self) -> None:
        """Soft: Minimize deviation from target hours per assegnazione (weight 15)."""
        weight = 15

        # Calculate weeks remaining until end of the anno formativo
        weeks_in_year = (self.context.anno_fine - self.context.week_start).days // 7
        if weeks_in_year <= 0:
            weeks_in_year = 1

        for asg in self.context.assegnazioni:
            if asg.ore_residue <= 0:
                continue

            # Target: spread residual hours evenly across remaining weeks
            ore_target = max(1, asg.ore_residue // weeks_in_year)

            # Deroga: "Riduci ore docente a contratto" - halve this week's
            # target for the affected CONTRATTO docente(i), steering the
            # optimizer toward assigning them fewer hours this run.
            if (
                self.context.docenti_map.get(asg.docente_id) == "CONTRATTO"
                and self._deroga_active("reduce_contract_hours", docente_id=asg.docente_id)
            ):
                ore_target = max(1, ore_target // 2)

            target_detail = (
                f"monte ore residuo {asg.ore_residue}h su {weeks_in_year} "
                f"settiman{'a' if weeks_in_year == 1 else 'e'} rimanenti"
            )
            if ore_target != max(1, asg.ore_residue // weeks_in_year):
                target_detail += ", dimezzato dalla deroga sulle ore a contratto"

            # Sum hours assigned this week
            slots_for_asg = [
                self.x[(asg.assegnazione_id, giorno, ora)]
                for giorno in range(5)
                for ora in range(6)
                if (asg.assegnazione_id, giorno, ora) in self.x
            ]

            if slots_for_asg:
                ore_assigned = sum(slots_for_asg)

                # Create deviation var: |ore_assigned - ore_target|
                deviation = self.model.NewIntVar(0, asg.ore_residue, f"deviation_{asg.assegnazione_id}")
                self.model.Add(deviation >= ore_assigned - ore_target)
                self.model.Add(deviation >= ore_target - ore_assigned)

                self.soft_penalties.append(SoftPenalty(
                    var=deviation, weight=weight, kind="ore_target_deviation",
                    description=(
                        f"Ore di {asg.docente_nome} su {asg.classe_nome}/{asg.materia_nome} "
                        f"lontane dal target settimanale ({ore_target}h)"
                    ),
                    classe_id=asg.classe_id, docente_id=asg.docente_id,
                    hour_vars=slots_for_asg, ore_target=ore_target,
                    target_detail=target_detail,
                    docente_tipo=self.context.docenti_map.get(asg.docente_id),
                ))

    def _soft_contractor_gaps(self) -> None:
        """Soft: Minimize gaps (hole hours) for contractors (weight 12)."""
        weight = 12

        contractor_asgs = [
            asg for asg in self.context.assegnazioni
            if self.context.docenti_map.get(asg.docente_id) == "CONTRATTO"
        ]

        for docente_id in set(asg.docente_id for asg in contractor_asgs):
            # Deroga: "Autorizza uscita anticipata" - stop penalizing gaps
            # for this docente (or everyone, if unscoped): they're allowed
            # to leave and come back rather than needing a contiguous block.
            if self._deroga_active("authorize_early_exit", docente_id=docente_id):
                continue

            docente_asgs = [asg for asg in contractor_asgs if asg.docente_id == docente_id]
            docente_nome = docente_asgs[0].docente_nome if docente_asgs else docente_id

            for giorno in range(5):
                # Find first and last hours with slots
                all_hours = [
                    ora for asg in docente_asgs
                    for ora in range(6)
                    if (asg.assegnazione_id, giorno, ora) in self.x
                ]

                if len(all_hours) < 2:
                    continue

                first_hour = min(all_hours)
                last_hour = max(all_hours)

                # Add penalty for gaps
                # Simplified: for each gap hour, add small penalty
                for ora in range(first_hour, last_hour):
                    no_slot_vars = [
                        (1 - self.x[(asg.assegnazione_id, giorno, ora)])
                        for asg in docente_asgs
                        if (asg.assegnazione_id, giorno, ora) in self.x
                    ]

                    if no_slot_vars:
                        gap_penalty = self.model.NewIntVar(0, len(no_slot_vars), f"gap_{docente_id}_{giorno}_{ora}")
                        self.model.Add(gap_penalty >= sum(no_slot_vars) - len(no_slot_vars) + 1)
                        self.soft_penalties.append(SoftPenalty(
                            var=gap_penalty, weight=weight // 6, kind="contractor_gap",  # distribute weight
                            description=(
                                f"Buchi orari per {docente_nome} (contratto) "
                                f"({GIORNI_NOMI_IT[GiornoEnum(giorno).name]})"
                            ),
                            docente_id=docente_id, giorno=giorno,
                            suggested_action={
                                "action_type": "authorize_early_exit", "label": "Autorizza uscita anticipata",
                            },
                        ))

    def _soft_avoid_single_classe_day(self) -> None:
        """
        Soft: a docente who teaches more than one classe shouldn't spend an
        entire day with only one of them (weight 10, same tier as
        _soft_teoria_consecutive) - admin-observed 2026-09-18 as an
        undesirable default pattern, but explicitly not a hard rule: the
        admin may want exactly this on purpose (e.g. a project day), so the
        "authorize_single_classe_day" deroga (scoped to that docente) turns
        the penalty off for a single generation run.

        Only meaningful for a docente with >=2 distinct classi overall - one
        who only ever teaches a single classe has no alternative, so isn't
        penalized. Only flags a day with a real number of hours (>= 3): a
        lone hour or two is trivially "all with one classe" and isn't the
        monotony pattern being discouraged.
        """
        weight = 10
        MIN_HOURS = 3

        skip_ids = self._paired_assignment_ids_to_dedupe()

        asgs_by_docente: Dict[str, List[AssegnazioneDati]] = {}
        for asg in self.context.assegnazioni:
            asgs_by_docente.setdefault(asg.docente_id, []).append(asg)

        for docente_id, asgs in asgs_by_docente.items():
            classi_ids = {a.classe_id for a in asgs}
            if len(classi_ids) < 2:
                continue

            if self._deroga_active("authorize_single_classe_day", docente_id=docente_id):
                continue

            docente_nome = asgs[0].docente_nome

            for giorno in range(5):
                total_hours = sum(
                    self.x[(a.assegnazione_id, giorno, ora)]
                    for a in asgs
                    if a.assegnazione_id not in skip_ids
                    for ora in range(6)
                    if (a.assegnazione_id, giorno, ora) in self.x
                )

                for classe_id in classi_ids:
                    classe_asgs = [a for a in asgs if a.classe_id == classe_id]
                    hours_with_classe = sum(
                        self.x[(a.assegnazione_id, giorno, ora)]
                        for a in classe_asgs
                        for ora in range(6)
                        if (a.assegnazione_id, giorno, ora) in self.x
                    )
                    # hours_with_classe is always <= total_hours (it's a
                    # subset of the same day's hours), so this is >= 0.
                    other_hours = total_hours - hours_with_classe

                    # has_others == 1 iff the docente also worked a
                    # DIFFERENT classe that day. Reified via >=1/==0 (not
                    # a strict "<" against total_hours) so a day with zero
                    # hours worked at all (other_hours == 0, same as a day
                    # entirely with this classe) doesn't force a
                    # contradiction - a docente not working a giorno at all
                    # must stay a legitimate, unpenalized option.
                    has_others = self.model.NewBoolVar(f"has_other_classe_{docente_id}_{classe_id}_{giorno}")
                    self.model.Add(other_hours >= 1).OnlyEnforceIf(has_others)
                    self.model.Add(other_hours == 0).OnlyEnforceIf(has_others.Not())

                    enough_hours = self.model.NewBoolVar(f"enough_hours_{docente_id}_{classe_id}_{giorno}")
                    self.model.Add(total_hours >= MIN_HOURS).OnlyEnforceIf(enough_hours)
                    self.model.Add(total_hours < MIN_HOURS).OnlyEnforceIf(enough_hours.Not())

                    # is_mono == 1 iff every one of the docente's hours that
                    # day (at least MIN_HOURS of them) was with this classe.
                    is_mono = self.model.NewBoolVar(f"mono_classe_{docente_id}_{classe_id}_{giorno}")
                    self.model.AddBoolAnd([has_others.Not(), enough_hours]).OnlyEnforceIf(is_mono)
                    self.model.AddBoolOr([has_others, enough_hours.Not()]).OnlyEnforceIf(is_mono.Not())

                    self.soft_penalties.append(SoftPenalty(
                        var=is_mono, weight=weight, kind="single_classe_day",
                        description=(
                            f"{docente_nome} passa tutta la giornata con una sola classe "
                            f"({classe_asgs[0].classe_nome}, "
                            f"{GIORNI_NOMI_IT[GiornoEnum(giorno).name]})"
                        ),
                        docente_id=docente_id, classe_id=classe_id, giorno=giorno,
                        suggested_action={
                            "action_type": "authorize_single_classe_day",
                            "label": "Autorizza giornata mono-classe",
                        },
                    ))

    def solve_fixed(self, assigned_keys: Set[Tuple[str, int, int]], timeout_seconds: int = 10) -> str:
        """
        Solve the model with every decision variable pinned to a specific,
        already-decided assignment (e.g. the current schedule after a manual
        slot edit): 1 for keys in `assigned_keys`, 0 otherwise. Used to check
        whether a manual edit still satisfies every hard constraint, and to
        recompute the quality score against the same soft-constraint weights
        used at generation time, without re-exploring the search space
        (pinning every variable makes the solve trivial regardless of
        problem size).
        """
        if not self.model:
            raise ValueError("Model not built. Call build_model() first.")

        for key, var in self.x.items():
            self.model.Add(var == (1 if key in assigned_keys else 0))

        return self.solve(timeout_seconds=timeout_seconds)

    def solve(self, timeout_seconds: int = 60) -> str:
        """
        Solve the model.
        Returns: "OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN"
        """
        if not self.model:
            raise ValueError("Model not built. Call build_model() first.")

        logger.info(f"Solving with timeout {timeout_seconds}s...")

        self.solver = cp_model.CpSolver()
        self.solver.parameters.max_time_in_seconds = timeout_seconds

        self.status = self.solver.Solve(self.model)

        if self.status == cp_model.OPTIMAL:
            logger.info("Solver: OPTIMAL solution found")
            return "OPTIMAL"
        elif self.status == cp_model.FEASIBLE:
            logger.info("Solver: FEASIBLE solution found (not optimal)")
            return "FEASIBLE"
        elif self.status == cp_model.INFEASIBLE:
            logger.warning("Solver: INFEASIBLE (no solution exists)")
            return "INFEASIBLE"
        else:
            logger.warning("Solver: UNKNOWN status")
            return "UNKNOWN"

    def extract_solution(self) -> List[Dict]:
        """
        Extract solution from solver.
        Returns list of slots: [{"assegnazione_id", "docente_id", "classe_id", "materia_id", "giorno", "ora_inizio", "ora_fine", "accoppiata"}]
        """
        if self.status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            return []

        slots = []
        giorni_nomi = ["LUNEDI", "MARTEDI", "MERCOLEDI", "GIOVEDI", "VENERDI"]

        # Find all variables with value 1
        for (assegnazione_id, giorno, ora), var in self.x.items():
            if self.solver.Value(var) == 1:
                # Find assegnazione details
                asg = next(
                    (a for a in self.context.assegnazioni if a.assegnazione_id == assegnazione_id),
                    None
                )

                if not asg:
                    logger.warning(f"Assegnazione {assegnazione_id} not found")
                    continue

                # Check if accoppiata - only for the specific docente named on
                # the accoppiamento row, not any docente of that classe (see
                # ClasseAccoppiata's docstring: most of a paired class's hours
                # are still normal, independent lessons with its other docenti).
                accoppiata = False
                classe_accoppiata_id = None
                for c_a, c_b, mat, doc_id in self.context.classi_accoppiate:
                    if (asg.classe_id in (c_a, c_b) and asg.materia_id == mat
                            and doc_id == asg.docente_id):
                        accoppiata = True
                        classe_accoppiata_id = c_b if asg.classe_id == c_a else c_a
                        break

                slot = {
                    "assegnazione_id": assegnazione_id,
                    "docente_id": asg.docente_id,
                    "docente_nome": asg.docente_nome,
                    "classe_id": asg.classe_id,
                    "classe_nome": asg.classe_nome,
                    "materia_id": asg.materia_id,
                    "materia_nome": asg.materia_nome,
                    "materia_tipo": asg.materia_tipo,
                    "giorno": giorni_nomi[giorno],
                    "ora_inizio": 8 + ora,
                    "ora_fine": 8 + ora + 1,
                    "accoppiata": accoppiata,
                    "classe_accoppiata_id": classe_accoppiata_id,
                }
                slots.append(slot)

        logger.info(f"Extracted {len(slots)} slots from solution")
        return slots

    def calculate_quality_score(self) -> Tuple[float, str, int]:
        """
        Calculate quality score based on soft constraints satisfied.
        Returns: (score 0-100, level A/B/C, n_soft_conflicts)
        """
        if self.status not in [cp_model.OPTIMAL, cp_model.FEASIBLE]:
            return 0.0, "C", len(self.soft_penalties)

        # Count soft constraints satisfied
        soft_satisfied = 0
        soft_total = len(self.soft_penalties)

        for p in self.soft_penalties:
            if self.solver.Value(p.var) == 0:
                soft_satisfied += 1

        if soft_total == 0:
            score = 100.0
            n_conflicts = 0
        else:
            score = (soft_satisfied / soft_total) * 100.0
            n_conflicts = soft_total - soft_satisfied

        # Determine level
        if score > 95:
            level = "A"
        elif score > 80:
            level = "B"
        else:
            level = "C"

        logger.info(f"Quality score: {score:.1f}% ({soft_satisfied}/{soft_total} soft constraints), level {level}")

        return score, level, n_conflicts

    def get_conflicts(self) -> List[Dict[str, Any]]:
        """
        Human-readable list of the soft-constraint violations in the
        current solution (frontend/src/lib/types.ts's Conflict[], shown in
        the "Conflitti" panel). Deduplicated per (kind, classe_id,
        docente_id, giorno) so a run of consecutive violated hours/windows
        doesn't flood the UI with near-identical entries - one entry per
        distinct problem area instead.
        """
        if self.status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return []

        seen: Set[Tuple] = set()
        conflicts: List[Dict[str, Any]] = []

        for i, p in enumerate(self.soft_penalties):
            if self.solver.Value(p.var) <= 0:
                continue

            suggested_action = p.suggested_action
            description = p.description
            if p.kind == "ore_target_deviation":
                # Only suggest "reduce hours" when they're actually OVER
                # target (and only makes sense for a CONTRATTO docente);
                # under target has no quick-action fix.
                ore_assigned = sum(self.solver.Value(v) for v in (p.hour_vars or []))
                if p.ore_target is not None:
                    delta = ore_assigned - p.ore_target
                    description = (
                        f"{p.description.split(' lontane dal target')[0]}: "
                        f"{ore_assigned}h assegnate contro un target di {p.ore_target}h "
                        f"({'+' if delta > 0 else ''}{delta}h; {p.target_detail})"
                    )
                if p.docente_tipo == "CONTRATTO" and p.ore_target is not None and ore_assigned > p.ore_target:
                    suggested_action = {
                        "action_type": "reduce_contract_hours", "label": "Riduci ore docente a contratto",
                    }
                else:
                    suggested_action = None

            dedup_key = (p.kind, p.classe_id, p.docente_id, p.giorno)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            conflicts.append({
                "conflict_id": f"{p.kind}_{p.classe_id or ''}_{p.docente_id or ''}_{p.giorno}_{i}",
                "description": description,
                "suggested_action": suggested_action,
                # Scope so the frontend can highlight the offending cell(s) in
                # the grid (SlotLezioneResponse.conflitto), not just list the
                # conflict in the sidebar - see ScheduleService._mark_slot_conflicts.
                "classe_id": p.classe_id,
                "docente_id": p.docente_id,
                "giorno": GiornoEnum(p.giorno).name if p.giorno is not None else None,
            })

        return conflicts
