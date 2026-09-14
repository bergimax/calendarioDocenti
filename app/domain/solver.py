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
    flag_chiusura: bool = False


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
    classi_accoppiate: List[Tuple[str, str, str]]  # (classe_a_id, classe_b_id, materia_id)

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
    kind: str  # "teoria_consecutive" | "ore_target_deviation" | "contractor_gap"
    description: str
    classe_id: Optional[str] = None
    docente_id: Optional[str] = None
    giorno: Optional[int] = None
    suggested_action: Optional[Dict[str, str]] = None
    # ore_target_deviation only: the assigned-hours vars + target, to work
    # out (after solving) whether this docente is over or under target -
    # only "over" for a CONTRATTO docente gets a suggested_action.
    hour_vars: Optional[List[Any]] = None
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

        # Hard 2: Day capacity constraint
        self._constraint_day_capacity()

        # Hard 3: Paired classes
        self._constraint_paired_classes()

        # Hard 4: Teacher availability
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

    def _paired_assignment_ids_to_dedupe(self) -> Set[str]:
        """
        When the same docente teaches both sides of a classe-accoppiata for the
        common materia (the spec-intended case), _constraint_paired_classes
        forces their two assegnazioni to always be equal (x_a == x_b): they
        represent a single joint lesson, not two separate bookings. Without
        this, _constraint_no_double_booking would sum both into the same
        docente/giorno/ora slot and force the pair to always be 0 (sum <= 1
        vs. x_a == x_b == 1 is unsatisfiable). Returns the assegnazione_ids
        of the "B" side of such pairs, to be excluded from that sum.
        """
        skip_ids: Set[str] = set()
        for classe_a, classe_b, materia_id in self.context.classi_accoppiate:
            asg_a = next(
                (a for a in self.context.assegnazioni
                 if a.classe_id == classe_a and a.materia_id == materia_id),
                None,
            )
            asg_b = next(
                (a for a in self.context.assegnazioni
                 if a.classe_id == classe_b and a.materia_id == materia_id),
                None,
            )
            if asg_a and asg_b and asg_a.docente_id == asg_b.docente_id:
                skip_ids.add(asg_b.assegnazione_id)
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

    def _ore_max_for_classe_giorno(self, classe_id: str, giorno: int) -> int:
        """
        Resolve the daily hour cap for a classe on a given giorno.
        Looks for a calendar row scoped to this classe's gruppo first (a
        per-year-group PDF calendar), then falls back to a school-wide row
        (gruppo=None, e.g. a plain CSV calendar or an inferred closure), then
        to a hardcoded default if neither exists.
        """
        gruppo = self.context.classi_gruppo.get(classe_id)

        if gruppo is not None:
            for c in self.context.calendario:
                if c.giorno == giorno and c.gruppo == gruppo:
                    return 0 if c.flag_chiusura else c.ore_max_giornata

        for c in self.context.calendario:
            if c.giorno == giorno and c.gruppo is None:
                return 0 if c.flag_chiusura else c.ore_max_giornata

        return 6  # no calendar data at all for this day: default

    def _constraint_day_capacity(self) -> None:
        """Hard constraint 2: Per-class daily hours <= ore_max_giornata."""
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
                    self.model.Add(sum(hours_in_day) <= ore_max)

    def _constraint_paired_classes(self) -> None:
        """Hard constraint 3: Paired classes must have same docente/giorno/ora."""
        # Build map: (classe_a, classe_b, materia_id) -> True
        paired_set = set()
        for classe_a, classe_b, materia_id in self.context.classi_accoppiate:
            paired_set.add((classe_a, classe_b, materia_id))
            paired_set.add((classe_b, classe_a, materia_id))  # bidirectional

        # Find assegnazioni for paired classes
        for classe_a, classe_b, materia_id in self.context.classi_accoppiate:
            asg_a = next(
                (asg for asg in self.context.assegnazioni
                 if asg.classe_id == classe_a and asg.materia_id == materia_id),
                None
            )
            asg_b = next(
                (asg for asg in self.context.assegnazioni
                 if asg.classe_id == classe_b and asg.materia_id == materia_id),
                None
            )

            if asg_a and asg_b:
                # Must have same giorno/ora (docente should be same too)
                for giorno in range(5):
                    for ora in range(6):
                        key_a = (asg_a.assegnazione_id, giorno, ora)
                        key_b = (asg_b.assegnazione_id, giorno, ora)

                        if key_a in self.x and key_b in self.x:
                            self.model.Add(self.x[key_a] == self.x[key_b])

    def _constraint_teacher_availability(self) -> None:
        """Hard constraint 4: Respect teacher availability + ASSUNTO 8-14 range."""
        for asg in self.context.assegnazioni:
            docente_id = asg.docente_id
            docente_tipo = self.context.docenti_map.get(docente_id)

            # ASSUNTO: implicit (already limited to 0-5 which is 8-14)
            if docente_tipo == "ASSUNTO":
                continue

            # Deroga: "Deroga disponibilità" - admin override, skip enforcing
            # the recorded availability for this docente this run.
            if self._deroga_active("override_availability", docente_id=docente_id):
                continue

            # CONTRATTO: respect giorni_fasce
            disponibilita = self.context.disponibilita_map.get(docente_id)
            if not disponibilita:
                # No availability recorded -> treat as unavailable all week
                logger.warning(f"No availability found for CONTRATTO {docente_id}, treating as unavailable")
                for giorno in range(5):
                    for ora in range(6):
                        key = (asg.assegnazione_id, giorno, ora)
                        if key in self.x:
                            self.model.Add(self.x[key] == 0)
                continue

            # Check giorni_fasce for unavailable slots
            giorni_nomi = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi"]
            for giorno in range(5):
                giorno_nome = giorni_nomi[giorno]
                slots = disponibilita.giorni_fasce.get(giorno_nome, [])

                for slot in slots:
                    disponibile = slot.get("disponibile", False)
                    if disponibile:
                        continue

                    # Extract hour from time (e.g., "08:00" -> 8)
                    try:
                        ora_inizio = int(slot["ora_inizio"].split(":")[0])
                        hora_idx = ora_inizio - 8  # 8->0, 9->1, ..., 13->5
                        if 0 <= hora_idx < 6:
                            key = (asg.assegnazione_id, giorno, hora_idx)
                            if key in self.x:
                                self.model.Add(self.x[key] == 0)
                    except (ValueError, IndexError, KeyError):
                        logger.warning(f"Invalid time slot format: {slot}")

    def _constraint_exclude_stage(self) -> None:
        """Hard constraint 5: Exclude classes in stage from scheduling."""
        for giorno_data in self.context.calendario:
            if not giorno_data.flag_stage_classe_id:
                continue

            classe_in_stage = giorno_data.flag_stage_classe_id
            giorno = giorno_data.giorno

            # Find all asgs for this classe
            asgs_in_stage = [
                asg for asg in self.context.assegnazioni
                if asg.classe_id == classe_in_stage
            ]

            # Zero out all slots for this classe on this giorno
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

        # Soft 2: Blocchi pratica 3-6 ore (weight 8)
        self._soft_pratica_blocks()

        # Soft 3: Minimize deviation from ore_target per assegnazione (weight 15)
        self._soft_ore_target_deviation()

        # Soft 4: Minimize ore buche for contrattisti (weight 12)
        self._soft_contractor_gaps()

    def _soft_teoria_consecutive(self) -> None:
        """Soft: Theory max 2 consecutive hours."""
        weight = 10

        # Group asgs by materia_tipo = TEORIA
        teoria_asgs = [asg for asg in self.context.assegnazioni if asg.materia_tipo == "TEORIA"]

        for classe_id in self.context.classi_set:
            classe_teoria = [asg for asg in teoria_asgs if asg.classe_id == classe_id]
            classe_nome = classe_teoria[0].classe_nome if classe_teoria else classe_id

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
                        for asg in classe_teoria
                        for h in range(3)
                        if (asg.assegnazione_id, giorno, ora_start + h) in self.x
                    ]

                    if hours_in_window:
                        # Penalize if hours in window exceed the cap
                        excess = self.model.NewIntVar(0, 3, f"excess_teoria_{classe_id}_{giorno}_{ora_start}")
                        self.model.Add(excess >= sum(hours_in_window) - max_consecutive)
                        self.soft_penalties.append(SoftPenalty(
                            var=excess, weight=weight, kind="teoria_consecutive",
                            description=(
                                f"Troppe ore di teoria consecutive per {classe_nome} "
                                f"({GIORNI_NOMI_IT[GiornoEnum(giorno).name]})"
                            ),
                            classe_id=classe_id, giorno=giorno,
                            suggested_action={"action_type": "force_3_hours_theory", "label": "Forza 3 ore teoria"},
                        ))

    def _soft_pratica_blocks(self) -> None:
        """Soft: Practice should be in 3-6 hour blocks."""
        weight = 8

        # This is complex: we want continuous blocks of 3-6 hours for same (classe, docente, materia)
        # For MVP, simplify: minimize isolated practice hours (alone without before/after)

        pratica_asgs = [asg for asg in self.context.assegnazioni if asg.materia_tipo == "PRATICA"]

        for giorno in range(5):
            for ora in range(6):
                for asg in pratica_asgs:
                    key = (asg.assegnazione_id, giorno, ora)
                    if key not in self.x:
                        continue

                    # Check if this slot is isolated (no adjacent slots same asg)
                    has_before = (asg.assegnazione_id, giorno, ora - 1) in self.x and ora > 0
                    has_after = (asg.assegnazione_id, giorno, ora + 1) in self.x and ora < 5

                    # Isolated slot gets small penalty (can coexist with other asgs)
                    # For now, skip complex logic

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

                # Check if accoppiata
                accoppiata = False
                classe_accoppiata_id = None
                for c_a, c_b, mat in self.context.classi_accoppiate:
                    if asg.classe_id in [c_a, c_b] and asg.materia_id == mat:
                        accoppiata = True
                        classe_accoppiata_id = c_b if asg.classe_id == c_a else c_a
                        break

                slot = {
                    "assegnazione_id": assegnazione_id,
                    "docente_id": asg.docente_id,
                    "classe_id": asg.classe_id,
                    "materia_id": asg.materia_id,
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
            if p.kind == "ore_target_deviation":
                # Only suggest "reduce hours" when they're actually OVER
                # target (and only makes sense for a CONTRATTO docente);
                # under target has no quick-action fix.
                ore_assigned = sum(self.solver.Value(v) for v in (p.hour_vars or []))
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
                "description": p.description,
                "suggested_action": suggested_action,
            })

        return conflicts
