from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Tuple, Optional, Set
from enum import Enum
from ortools.sat.python import cp_model
import logging

logger = logging.getLogger(__name__)


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
    """Calendar day data for week."""
    data: date
    giorno: int  # 0-4
    ore_max_giornata: int
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


class ScheduleSolver:
    """
    Constraint Programming solver for school schedule generation.
    Uses Google OR-Tools CP-SAT solver.
    """

    def __init__(self, context: ScheduleContext):
        """Initialize solver with problem context."""
        self.context = context
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

        # 4. Set objective function
        if self.soft_penalties:
            self.model.Minimize(sum(penalty for penalty, _ in self.soft_penalties))

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

    def _constraint_no_double_booking(self) -> None:
        """Hard constraint 1: No teacher can teach 2 classes in same hour."""
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
                        if (asg.assegnazione_id, giorno, ora) in self.x
                    ]
                    if overlapping:
                        self.model.Add(sum(overlapping) <= 1)

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
                # Find max hours for this day
                cal_entry = next(
                    (c for c in self.context.calendario if c.giorno == giorno),
                    None
                )
                if not cal_entry:
                    continue

                # Closure days (holidays/extraordinary closures) have zero capacity
                ore_max = 0 if cal_entry.flag_chiusura else cal_entry.ore_max_giornata

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
                        # Penalize if >2 hours in window
                        excess = self.model.NewIntVar(0, 3, f"excess_teoria_{classe_id}_{giorno}_{ora_start}")
                        self.model.Add(excess >= sum(hours_in_window) - 2)
                        self.soft_penalties.append((excess, weight))

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

                self.soft_penalties.append((deviation, weight))

    def _soft_contractor_gaps(self) -> None:
        """Soft: Minimize gaps (hole hours) for contractors (weight 12)."""
        weight = 12

        contractor_asgs = [
            asg for asg in self.context.assegnazioni
            if self.context.docenti_map.get(asg.docente_id) == "CONTRATTO"
        ]

        for docente_id in set(asg.docente_id for asg in contractor_asgs):
            docente_asgs = [asg for asg in contractor_asgs if asg.docente_id == docente_id]

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
                        self.soft_penalties.append((gap_penalty, weight // 6))  # distribute weight

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

        for penalty, weight in self.soft_penalties:
            if self.solver.Value(penalty) == 0:
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
