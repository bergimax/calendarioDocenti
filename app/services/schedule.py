from sqlalchemy.orm import Session
from datetime import date, timedelta
from typing import Dict, Any, List, Optional
from app.repositories.schedule import ScheduleRepository
from app.domain.solver import ScheduleSolver
from app.schemas import ScheduleGenerateResponse, SlotLezioneResponse
import logging
import re

logger = logging.getLogger(__name__)

QUICK_ACTIONS = {
    "force_3_hours_theory",
    "reduce_contract_hours",
    "authorize_early_exit",
    "override_availability",
    "authorize_single_classe_day",
    "authorize_friday_late_start",
    "authorize_short_pratica_block",
}


class ScheduleService:
    """Business logic for schedule generation and management."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = ScheduleRepository(db)

    def generate_schedule(
        self, scuola_id: str, week_start: date, timeout_seconds: int = 60
    ) -> ScheduleGenerateResponse:
        """
        Generate optimal weekly schedule.

        Returns ScheduleGenerateResponse with:
        - status: "generated", "infeasible", "timeout", "error"
        - If generated: schedule_id, quality_score, quality_level, slots
        - If infeasible: conflicting_constraints, suggested_deroghe
        """
        logger.info(f"Generating schedule for school {scuola_id} week {week_start}")

        try:
            from app.models import OrarioSettimanale

            existing = self.db.query(OrarioSettimanale).filter(
                OrarioSettimanale.scuola_id == scuola_id,
                OrarioSettimanale.settimana_inizio == week_start,
            ).first()
            if existing and existing.stato == "APPROVATO":
                return ScheduleGenerateResponse(
                    status="error",
                    message="Schedule is approved and locked; cannot regenerate.",
                )

            # 1. Extract context from DB
            context = self.repo.get_week_context(scuola_id, week_start)

            if not context.assegnazioni:
                logger.warning("No assegnazioni found for this school")
                return ScheduleGenerateResponse(
                    status="error",
                    message="No teacher-class-subject assignments found. Setup incomplete.",
                )

            # 2. Build and solve model
            solver, status, relaxed = self._solve_with_fallback(
                context, timeout_seconds=timeout_seconds,
            )

            # 3. Handle results
            if status in ["OPTIMAL", "FEASIBLE"]:
                # Extract solution
                slots = solver.extract_solution()

                # Calculate quality
                quality_score, quality_level, n_conflicts = solver.calculate_quality_score()
                conflicts = solver.get_conflicts()
                self._mark_slot_conflicts(slots, conflicts)
                self._mark_slot_unavailability(slots, scuola_id, week_start)

                # Save to DB
                schedule_id = self.repo.save_generated_schedule(
                    scuola_id=scuola_id,
                    week_start=week_start,
                    slots=slots,
                    quality_score=quality_score,
                    quality_level=quality_level,
                    n_soft_conflicts=n_conflicts,
                )

                # Convert slots to response format
                slot_responses = [
                    SlotLezioneResponse(
                        slot_id="",  # will be assigned in DB, use temp id
                        classe_id=s["classe_id"],
                        classe_nome=s.get("classe_nome"),
                        docente_id=s["docente_id"],
                        docente_nome=s.get("docente_nome"),
                        materia_id=s["materia_id"],
                        materia_nome=s.get("materia_nome"),
                        materia_tipo=s.get("materia_tipo"),
                        giorno=s["giorno"],
                        ora_inizio=s["ora_inizio"],
                        ora_fine=s["ora_fine"],
                        accoppiata=s["accoppiata"],
                        classe_accoppiata_id=s.get("classe_accoppiata_id"),
                        conflitto=s.get("conflitto", False),
                        conflitto_chiavi=s.get("conflitto_chiavi", []),
                        indisponibile=s.get("indisponibile", False),
                    )
                    for s in slots
                ]

                logger.info(f"Schedule generated successfully: {schedule_id}")

                return ScheduleGenerateResponse(
                    status="generated",
                    schedule_id=schedule_id,
                    quality_score=quality_score,
                    quality_level=quality_level,
                    n_soft_conflicts=n_conflicts,
                    slots=slot_responses,
                    conflicts=conflicts,
                    stage_cells=self.repo._stage_cells_for_week(scuola_id, week_start),
                    message=(
                        "Nessun orario completo possibile: generato il migliore disponibile, "
                        "le ore non coperte e i vincoli forzati sono segnalati come conflitti."
                        if relaxed else None
                    ),
                )

            elif status == "INFEASIBLE":
                logger.warning("Solver: infeasible (no solution exists)")

                # Try to identify conflicting constraints
                conflicting = self._identify_conflicts(context)

                return ScheduleGenerateResponse(
                    status="infeasible",
                    message="Schedule generation failed: constraints are contradictory.",
                    conflicting_constraints=conflicting,
                    suggested_deroghe=self._suggest_deroghe(conflicting),
                )

            else:  # UNKNOWN or timeout
                logger.warning(f"Solver status: {status}")

                return ScheduleGenerateResponse(
                    status="timeout",
                    message="Solver did not converge within time limit (60s). Try again or adjust constraints.",
                )

        except ValueError as e:
            logger.error(f"Validation error: {e}")
            return ScheduleGenerateResponse(
                status="error",
                message=f"Validation error: {str(e)}",
            )

        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            return ScheduleGenerateResponse(
                status="error",
                message=f"Internal error: {str(e)}",
            )

    def get_schedule(self, scuola_id: str, week_start: date) -> Optional[Dict[str, Any]]:
        """
        Retrieve previously generated schedule. Returns None if no schedule
        exists for this week (the route maps that to 404).

        The response is the schedule's fields flattened at the top level
        (schedule_id, quality_score, slots, ...) - not nested under a
        "schedule" key - because the frontend fetches this directly as its
        `Schedule` type (frontend/src/lib/types.ts).
        """
        logger.info(f"Retrieving schedule for school {scuola_id} week {week_start}")

        schedule = self.repo.get_schedule_by_week(scuola_id, week_start)
        if not schedule:
            return None

        conflicts = self._apply_handled(
            schedule["schedule_id"],
            self._conflicts_for_persisted_schedule(scuola_id, week_start, schedule),
        )
        self._mark_slot_conflicts(schedule["slots"], conflicts)
        self._mark_slot_unavailability(schedule["slots"], scuola_id, week_start)
        return {"status": "found", "conflicts": conflicts, **schedule}

    def _conflicts_for_persisted_schedule(
        self, scuola_id: str, week_start: date, schedule: Dict[str, Any],
    ) -> list:
        """
        Recover the itemized soft-constraint conflicts for a schedule as
        currently persisted (get_schedule has no freshly-solved
        ScheduleSolver in hand the way generate/modify/quick-action do):
        rebuild the model and pin it to the persisted slots (see
        ScheduleSolver.solve_fixed), then read its soft_penalties. Returns
        [] if the persisted slots no longer satisfy the hard constraints
        (underlying data changed since) rather than raising.
        """
        from app.domain.solver import ScheduleSolver, GiornoEnum

        context = self.repo.get_week_context(scuola_id, week_start)
        if not context.assegnazioni:
            return []

        assigned_keys = set()
        for s in schedule["slots"]:
            asg = next(
                (a for a in context.assegnazioni
                 if a.classe_id == s["classe_id"] and a.materia_id == s["materia_id"]
                 and a.docente_id == s["docente_id"]),
                None,
            )
            if asg:
                assigned_keys.add((asg.assegnazione_id, GiornoEnum[s["giorno"]].value, s["ora_inizio"] - 8))

        solver, status, _ = self._solve_with_fallback(context, fixed_keys=assigned_keys)
        if status not in ("OPTIMAL", "FEASIBLE"):
            logger.warning(
                f"Persisted schedule for {week_start} violates a hard constraint ({status}); "
                "conflicts cannot be computed"
            )
            return []

        return solver.get_conflicts()

    # ===== Helper Methods =====

    @staticmethod
    def _mark_slot_conflicts(slots: List[Dict[str, Any]], conflicts: List[Dict[str, Any]]) -> None:
        """
        Set each slot dict's "conflitto" (frontend/src/routes/orario.tsx
        colors the cell red on it) and "conflitto_chiavi" (which conflicts it
        belongs to, so a click can show their messages) in place, when the
        slot falls within the scope of one of `conflicts` (see
        ScheduleSolver.get_conflicts). Without this, conflicts were only ever
        visible in the sidebar list, never on the grid itself.
        """
        # "classe_unfilled" conflicts ("ore" set) are about hours with no
        # lesson: those cells are painted red on their own, the lessons the
        # classe does have that day stay normal.
        scopes = [
            (c.get("chiave"), c.get("classe_id"), c.get("docente_id"), c.get("giorno"), c.get("ore_slot"))
            for c in conflicts
            if (c.get("classe_id") or c.get("docente_id")) and not c.get("ore")
        ]

        def in_scope(s: Dict[str, Any], classe_id, docente_id, giorno, ore_slot=None) -> bool:
            if ore_slot:
                # a forced lesson's conflict: only the lessons at those hours
                return s.get("giorno") == giorno and s.get("ora_inizio") in ore_slot and (
                    (classe_id and s.get("classe_id") == classe_id)
                    or (docente_id and s.get("docente_id") == docente_id)
                )
            if giorno:
                # a day-scoped conflict: any lesson of that classe or docente that day
                return s.get("giorno") == giorno and (
                    (classe_id and s.get("classe_id") == classe_id)
                    or (docente_id and s.get("docente_id") == docente_id)
                )
            # no day (e.g. a docente's weekly hours off target in one classe):
            # exactly that classe+docente's lessons. With only one of the two
            # there is no sensible cell to point at, so leave it unmarked.
            return bool(
                classe_id and docente_id
                and s.get("classe_id") == classe_id and s.get("docente_id") == docente_id
            )

        avvisi = {c.get("chiave") for c in conflicts if c.get("avviso")}
        for s in slots:
            chiavi = [chiave for chiave, *scope in scopes if chiave and in_scope(s, *scope)]
            s["conflitto_chiavi"] = chiavi
            # Le ore in più/in meno di un docente sono un avviso (cella gialla), non un conflitto.
            s["conflitto"] = any(k not in avvisi for k in chiavi)
            s["avviso"] = not s["conflitto"] and bool(chiavi)

    def _apply_handled(self, orario_id: str, conflicts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Drop the conflicts the admin already handled (ConflittoGestito):
        approved ones entirely, and, for uncovered hours, the hours they chose
        to leave free (a conflict left with no hour goes away too).
        """
        from app.models import ConflittoGestito

        rows = self.db.query(ConflittoGestito).filter(
            ConflittoGestito.orario_settimanale_id == orario_id
        ).all()
        if not rows:
            return conflicts
        approved = {r.chiave for r in rows if r.azione == "APPROVATO"}
        freed = {r.chiave for r in rows if r.azione == "LIBERA"}

        result = []
        for c in conflicts:
            if c.get("chiave") in approved:
                continue
            if c.get("ore"):
                ore = [h for h in c["ore"] if f"libera|{c['classe_id']}|{c['giorno']}|{h}" not in freed]
                if not ore:
                    continue
                if len(ore) != len(c["ore"]):
                    c = {
                        **c, "ore": ore,
                        "description": re.sub(r"\d+ ora/e non coperta/e \([^)]*\)",
                                              f"{len(ore)} ora/e non coperta/e ({', '.join(f'{h}:00' for h in ore)})",
                                              c["description"]),
                    }
            result.append(c)
        return result

    def assignable_for_classe(self, scuola_id: str, week_start: date, classe_id: str) -> List[Dict[str, Any]]:
        """The docente/materia pairs assigned to a classe (what can be put in one of its free hours)."""
        context = self.repo.get_week_context(scuola_id, week_start)
        return sorted(
            (
                {
                    "docente_id": a.docente_id, "docente_nome": a.docente_nome,
                    "materia_id": a.materia_id, "materia_nome": a.materia_nome,
                    "ore_residue": a.ore_residue,
                }
                for a in context.assegnazioni if a.classe_id == classe_id
            ),
            key=lambda r: (r["docente_nome"] or "", r["materia_nome"] or ""),
        )

    def _day_max_violation(self, context, classe_id: str, giorno: str, count_after: int) -> Optional[str]:
        """
        Why a classe can't have `count_after` lessons on `giorno`, or None.
        The calendar's daily maximum is a rule a manual choice can't break
        (a later ingresso is fine, more hours than the day allows is not).
        """
        from app.domain.solver import ScheduleSolver, GiornoEnum, GIORNI_NOMI_IT

        ore_max = ScheduleSolver(context)._ore_max_for_classe_giorno(classe_id, GiornoEnum[giorno].value)
        if count_after <= ore_max:
            return None
        nome = next((a.classe_nome for a in context.assegnazioni if a.classe_id == classe_id), classe_id)
        giorno_it = GIORNI_NOMI_IT.get(giorno, giorno)
        if ore_max == 0:
            return f"{nome} non ha lezione {giorno_it}: è un giorno di chiusura o di stage."
        return (
            f"{nome}, {giorno_it}: la giornata prevede al massimo {ore_max} ore e con questa lezione "
            f"sarebbero {count_after}. Per assegnare quest'ora libera prima un'altra ora della stessa "
            "giornata (un ingresso posticipato è consentito, superare il massimo di ore no)."
        )

    def assign_slot(
        self, scuola_id: str, week_start: date, classe_id: str, giorno: str, ora_inizio: int,
        docente_id: str, materia_id: str,
    ) -> Dict[str, Any]:
        """
        Manual assignment ("forzatura") of a lesson to a free hour. The
        result is checked like a manual edit (solve_fixed with the
        best-effort fallback): rules the solver can relax (availability,
        target hours, Friday start, ...) don't block it, they come back as
        conflicts, and so do the ones a manual choice may break (an hour
        outside the day's calendar, a docente in two classi, hours over the
        monte ore): the admin decides with approve/reject. What is refused,
        with the reason: more lessons than the classe's daily maximum (a
        later ingresso is allowed, more hours are not).

        A docente in a paired (accoppiata) lesson teaches every classe of the
        group at once, so the lesson is assigned to all of them; a different
        lesson already sitting in that hour of a partner classe is replaced
        (reported in the response's "message").
        """
        from app.models import OrarioSettimanale, SlotLezione, ConflittoGestito, AuditLog
        from app.domain.solver import GiornoEnum

        orario = self.db.query(OrarioSettimanale).filter(
            OrarioSettimanale.scuola_id == scuola_id,
            OrarioSettimanale.settimana_inizio == week_start,
        ).first()
        if not orario:
            return {"status": "error", "message": "No schedule found for this week"}
        if orario.stato == "APPROVATO":
            return {"status": "error", "message": "Schedule is approved and locked from modifications"}
        if giorno not in GiornoEnum.__members__:
            return {"status": "error", "message": f"Invalid giorno: {giorno!r}"}
        if not (8 <= ora_inizio <= 13):
            return {"status": "error", "message": f"Invalid ora_inizio: {ora_inizio} (must be 8-13)"}

        context = self.repo.get_week_context(scuola_id, week_start)
        asg_of = {
            (a.classe_id, a.docente_id, a.materia_id): a for a in context.assegnazioni
        }
        classe_nomi = {a.classe_id: a.classe_nome for a in context.assegnazioni}
        target_asg = asg_of.get((classe_id, docente_id, materia_id))
        if not target_asg:
            return {"status": "error", "message": "Il docente non ha questa materia assegnata per la classe."}

        # The joint-lesson group: classi paired for this docente + materia.
        group = {classe_id}
        grew = True
        while grew:
            grew = False
            for c_a, c_b, mat, doc in context.classi_accoppiate:
                if doc == docente_id and mat == materia_id and (c_a in group) != (c_b in group):
                    group.update((c_a, c_b))
                    grew = True

        slots = list(orario.slot_lezioni)
        at_hour = [s for s in slots if s.giorno == giorno and s.ora_inizio == ora_inizio]
        if any(s.classe_id == classe_id for s in at_hour):
            return {"status": "error", "message": "Quest'ora ha già una lezione: modificala dal pannello."}

        to_remove: List[Any] = []
        replaced: List[str] = []
        to_add: List[str] = []  # classe ids that get the new lesson
        for c in sorted(group):
            if (c, docente_id, materia_id) not in asg_of:
                return {
                    "status": "error",
                    "message": f"La classe {classe_nomi.get(c, c)} (accoppiata) non ha questa materia "
                               "assegnata a questo docente.",
                }
            existing = next((s for s in at_hour if s.classe_id == c), None)
            if existing is None:
                to_add.append(c)
            elif existing.docente_id == docente_id and existing.materia_id == materia_id:
                continue  # that classe already has this very lesson
            else:
                # replace the partner classe's lesson: all of that docente's
                # lessons at this hour go, they may be a joint lesson too
                for j in at_hour:
                    if j.docente_id == existing.docente_id and j not in to_remove:
                        to_remove.append(j)
                        replaced.append(f"{classe_nomi.get(j.classe_id, j.classe_id)} "
                                        f"({j.docente.nome if j.docente else j.docente_id})")
                to_add.append(c)

        # The day's maximum hours cannot be forced: explain why instead.
        for c in to_add:
            after = sum(
                1 for s in slots
                if s.classe_id == c and s.giorno == giorno and s not in to_remove
            ) + 1
            reason = self._day_max_violation(context, c, giorno, after)
            if reason:
                return {"status": "error", "message": reason}

        assigned_keys = set()
        for s in slots:
            if s in to_remove:
                continue
            asg = asg_of.get((s.classe_id, s.docente_id, s.materia_id))
            if asg:
                assigned_keys.add((asg.assegnazione_id, GiornoEnum[s.giorno].value, s.ora_inizio - 8))
        for c in to_add:
            assigned_keys.add((asg_of[(c, docente_id, materia_id)].assegnazione_id,
                               GiornoEnum[giorno].value, ora_inizio - 8))

        solver, status, _ = self._solve_with_fallback(context, fixed_keys=assigned_keys)
        if status not in ("OPTIMAL", "FEASIBLE"):
            return {
                "status": "error",
                "message": "Assegnazione non possibile: viola una regola non derogabile del modello.",
            }

        quality_score, quality_level, n_conflicts = solver.calculate_quality_score()
        try:
            for j in to_remove:
                self.db.delete(j)
            paired = len(group) > 1
            for c in to_add:
                partner = next((g for g in sorted(group) if g != c), None) if paired else None
                self.db.add(SlotLezione(
                    orario_settimanale_id=orario.id, classe_id=c, docente_id=docente_id,
                    materia_id=materia_id, giorno=giorno, ora_inizio=ora_inizio, ora_fine=ora_inizio + 1,
                    accoppiata=paired, classe_accoppiata_id=partner,
                ))
            # these hours are no longer ones the admin chose to leave free
            self.db.query(ConflittoGestito).filter(
                ConflittoGestito.orario_settimanale_id == orario.id,
                ConflittoGestito.chiave.in_([f"libera|{c}|{giorno}|{ora_inizio}" for c in group]),
            ).delete(synchronize_session=False)
            orario.quality_score = quality_score
            orario.quality_level = quality_level
            orario.n_conflitti_soft = n_conflicts
            self.db.add(AuditLog(
                scuola_id=scuola_id, orario_settimanale_id=orario.id, azione="ASSIGN_SLOT",
                dettagli={"classe_id": classe_id, "giorno": giorno, "ora_inizio": ora_inizio,
                          "docente_id": docente_id, "materia_id": materia_id,
                          "classi": to_add, "sostituite": replaced},
            ))
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error assigning slot: {e}")
            return {"status": "error", "message": str(e)}

        result = self.get_schedule(scuola_id, week_start)
        notes = []
        if len(to_add) > 1:
            notes.append("Assegnata anche alle classi accoppiate: " + ", ".join(
                classe_nomi.get(c, c) for c in to_add if c != classe_id))
        if replaced:
            notes.append("Sostituite le lezioni di: " + "; ".join(replaced))
        result["message"] = ". ".join(notes) or None
        return result

    def approve_conflicts(self, scuola_id: str, week_start: date, chiavi: List[str]) -> Dict[str, Any]:
        """Approve conflicts: they disappear and their cells go back to normal."""
        return self._handle_conflict(scuola_id, week_start, approve=chiavi)

    def reject_conflict(
        self, scuola_id: str, week_start: date, classe_id: str, giorno: str, ora_inizio: int,
    ) -> Dict[str, Any]:
        """Reject: the lesson at that classe/giorno/ora (if any) is removed and the hour left free."""
        return self._handle_conflict(scuola_id, week_start, reject=(classe_id, giorno, ora_inizio))

    def _expand_to_paired_classes(self, scuola_id: str, week_start: date, chiavi: List[str]) -> List[str]:
        """
        A docente teaching a paired (accoppiata) lesson has one conflict per
        classe of the group, all about the same hours. Approving one should
        settle them all, so add the same conflict (kind, docente, giorno) for
        every classe paired with the approved one for that docente.
        """
        context = self.repo.get_week_context(scuola_id, week_start)
        expanded = list(chiavi)
        current = None  # current conflicts, fetched only if a classe-only conflict needs them
        for chiave in chiavi:
            parts = chiave.split("|")
            if len(parts) == 4 and parts[1] and not parts[2] and parts[3]:
                # a classe-level conflict without a docente (e.g. a forced hour
                # outside the day): settle the same conflict, on the same
                # hours, of the classi it is paired with.
                if current is None:
                    current = (self.get_schedule(scuola_id, week_start) or {}).get("conflicts", [])
                mine = next((c for c in current if c["chiave"] == chiave), None)
                if not mine or not mine.get("ore_slot"):
                    continue
                group = {parts[1]}
                grew = True
                while grew:
                    grew = False
                    for c_a, c_b, _mat, _doc in context.classi_accoppiate:
                        if (c_a in group) != (c_b in group):
                            group.update((c_a, c_b))
                            grew = True
                for c in current:
                    ck = c["chiave"].split("|")
                    if (c["chiave"] not in expanded and ck[0] == parts[0] and ck[1] in group
                            and ck[3] == parts[3] and c.get("ore_slot") == mine["ore_slot"]):
                        expanded.append(c["chiave"])
                continue
            if len(parts) != 4 or not parts[1] or not parts[2]:
                continue
            kind, classe_id, docente_id, giorno = parts
            group = {classe_id}
            grew = True
            while grew:
                grew = False
                for c_a, c_b, _mat, doc in context.classi_accoppiate:
                    if doc == docente_id and (c_a in group) != (c_b in group):
                        group.update((c_a, c_b))
                        grew = True
            for c in group - {classe_id}:
                other = f"{kind}|{c}|{docente_id}|{giorno}"
                if other not in expanded:
                    expanded.append(other)
        return expanded

    def _handle_conflict(
        self, scuola_id: str, week_start: date, approve: Optional[List[str]] = None,
        reject: Optional[tuple] = None,
    ) -> Dict[str, Any]:
        from app.models import OrarioSettimanale, SlotLezione, ConflittoGestito, AuditLog

        orario = self.db.query(OrarioSettimanale).filter(
            OrarioSettimanale.scuola_id == scuola_id,
            OrarioSettimanale.settimana_inizio == week_start,
        ).first()
        if not orario:
            return {"status": "error", "message": "No schedule found for this week"}
        if orario.stato == "APPROVATO":
            return {"status": "error", "message": "Schedule is approved and locked from modifications"}

        try:
            if approve:
                approve = self._expand_to_paired_classes(scuola_id, week_start, approve)
                for chiave in approve:
                    self.db.add(ConflittoGestito(
                        orario_settimanale_id=orario.id, chiave=chiave, azione="APPROVATO",
                    ))
                dettagli = {"chiavi": approve}
                azione = "APPROVE_CONFLICT"
            else:
                classe_id, giorno, ora = reject
                slot = self.db.query(SlotLezione).filter(
                    SlotLezione.orario_settimanale_id == orario.id,
                    SlotLezione.classe_id == classe_id,
                    SlotLezione.giorno == giorno,
                    SlotLezione.ora_inizio == ora,
                ).first()
                classi = {classe_id}
                if slot:
                    # A docente can only be in one place at a time, except in
                    # a joint (paired) lesson, which can span 2+ classi (a
                    # 4-way group is several ClasseAccoppiata pairs). So every
                    # lesson of this docente at this giorno/ora is the same
                    # joint lesson: free all of them, or the paired-class rule
                    # would break and the schedule could no longer be checked.
                    joint = self.db.query(SlotLezione).filter(
                        SlotLezione.orario_settimanale_id == orario.id,
                        SlotLezione.giorno == giorno,
                        SlotLezione.ora_inizio == ora,
                        SlotLezione.docente_id == slot.docente_id,
                    ).all()
                    classi.update(j.classe_id for j in joint)
                    for j in joint:
                        self.db.delete(j)
                for c in classi:
                    self.db.add(ConflittoGestito(
                        orario_settimanale_id=orario.id, chiave=f"libera|{c}|{giorno}|{ora}", azione="LIBERA",
                    ))
                dettagli = {"classe_id": classe_id, "giorno": giorno, "ora_inizio": ora}
                azione = "REJECT_CONFLICT"

            self.db.add(AuditLog(
                scuola_id=scuola_id, orario_settimanale_id=orario.id, azione=azione, dettagli=dettagli,
            ))
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error handling conflict: {e}")
            return {"status": "error", "message": str(e)}

        return self.get_schedule(scuola_id, week_start)

    def _mark_slot_unavailability(
        self, slots: List[Dict[str, Any]], scuola_id: str, week_start: date,
    ) -> None:
        """
        Set each slot dict's "indisponibile" key in place: True when the
        docente's recorded disponibilita for that exact giorno + hour is
        marked unavailable. Checked per hour straight against the stored
        availability (not via soft conflicts, which are scoped to a whole
        docente/classe + day), so the grid can tell a real availability
        violation apart from any other conflict. Docenti with no record
        (ASSUNTO, implicitly 8-14) are never flagged.
        """
        from app.models import DisponibilitaSettimanale

        unavailable = set()
        rows = self.db.query(DisponibilitaSettimanale).filter(
            DisponibilitaSettimanale.scuola_id == scuola_id,
            DisponibilitaSettimanale.settimana_inizio == week_start,
        ).all()
        for row in rows:
            for giorno, fasce in (row.giorni_fasce or {}).items():
                for f in fasce:
                    if f.get("disponibile", True):
                        continue
                    try:
                        unavailable.add((row.docente_id, giorno.upper(), int(f["ora_inizio"].split(":")[0])))
                    except (ValueError, KeyError, AttributeError):
                        continue
        for s in slots:
            s["indisponibile"] = any(
                (s["docente_id"], str(s["giorno"]).upper(), h) in unavailable
                for h in range(s["ora_inizio"], s["ora_fine"])
            )

    def _solve_with_fallback(
        self, context, timeout_seconds: int = 60, fixed_keys=None, **solver_kwargs,
    ):
        """
        Solve with every classroom hour required to be filled; if that is
        INFEASIBLE, solve again in best-effort mode (ScheduleSolver's
        `best_effort`) so the admin still gets the fullest timetable
        possible, with the uncovered hours reported as conflicts.
        `fixed_keys` pins the assignment (solve_fixed) instead of searching.
        Returns (solver, status, relaxed).
        """
        from app.domain.solver import ScheduleSolver
        from app.services.soft_weights import SoftWeightService

        # weights learned from the admin's ratings (defaults until any is applied)
        solver_kwargs.setdefault("soft_weights", SoftWeightService(self.db).active_weights())

        def run(best_effort: bool, forced: bool = False):
            solver = ScheduleSolver(
                context, best_effort=best_effort,
                # evaluating a decided schedule: an hour the admin freed in
                # the middle of a day is not a reason to reject it
                allow_gaps=best_effort and fixed_keys is not None,
                forced=forced,
                **solver_kwargs,
            )
            solver.build_model()
            if fixed_keys is not None:
                return solver, solver.solve_fixed(fixed_keys)
            return solver, solver.solve(timeout_seconds=timeout_seconds)

        solver, status = run(False)
        if status != "INFEASIBLE":
            return solver, status, False

        logger.warning("Strict model INFEASIBLE, retrying in best-effort mode")
        solver, status = run(True)
        if status == "INFEASIBLE" and fixed_keys is not None:
            # a schedule with lessons forced by hand: report what they break
            logger.warning("Best-effort INFEASIBLE for a fixed schedule, evaluating in forced mode")
            solver, status = run(True, forced=True)
        return solver, status, status in ("OPTIMAL", "FEASIBLE")

    def _identify_conflicts(self, context) -> list:
        """
        Attempt to identify which constraints conflict.
        This is a best-effort heuristic.
        """
        conflicts = []

        # Check 1: Are there any valid slot combinations?
        # For each assegnazione, check if at least 1 slot is feasible

        for asg in context.assegnazioni:
            has_feasible = False
            disp = None

            # Quick check: if ore_residue is 0, no slots possible
            if asg.ore_residue <= 0:
                has_feasible = False
            else:
                # Check availability
                disp = context.disponibilita_map.get(asg.docente_id)
                if disp:
                    # Has some availability
                    has_feasible = True
                else:
                    # CONTRATTO with no availability -> no slots
                    if asg.docente_tipo == "CONTRATTO":
                        has_feasible = False
                    else:
                        has_feasible = True

            if not has_feasible:
                conflicts.append(
                    f"{asg.docente_nome} ({asg.classe_nome}/{asg.materia_nome}): "
                    f"no feasible slot (ore_residue={asg.ore_residue}, "
                    f"disponibilita={'none' if not disp else 'available'})"
                )

        return conflicts

    def _suggest_deroghe(self, conflicting: list) -> list:
        """
        Suggest deroghe (exemptions) to resolve conflicts.
        """
        suggestions = []

        for conflict_msg in conflicting:
            if "ore_residue" in conflict_msg:
                suggestions.append("Reduce expected hours for this assignment")

            if "no feasible slot" in conflict_msg:
                suggestions.append("Extend teacher availability or reduce workload")

        # Deduplicate
        return list(set(suggestions))

    def scale_monte_ore(self, scuola_id: str, orario) -> Dict[str, int]:
        """
        Add every lesson of `orario` as 1 delivered hour to ore_erogate of its
        assegnazione (classe + materia + docente). Does not commit and does not
        check whether the week was already scaled: callers (approve_schedule,
        scripts/backfill_ore_erogate.py) own that.
        """
        from sqlalchemy import func
        from app.models import SlotLezione, MonteOreAnnuale

        # Lessons held this week per (classe, materia, docente).
        rows = (
            self.db.query(
                SlotLezione.classe_id, SlotLezione.materia_id, SlotLezione.docente_id,
                func.count(SlotLezione.id),
            )
            .filter(SlotLezione.orario_settimanale_id == orario.id)
            .group_by(SlotLezione.classe_id, SlotLezione.materia_id, SlotLezione.docente_id)
            .all()
        )
        ore_scalate = 0
        aggiornate = 0
        senza_monte = 0
        for classe_id, materia_id, docente_id, n in rows:
            monte = self.db.query(MonteOreAnnuale).filter_by(
                scuola_id=scuola_id, classe_id=classe_id,
                materia_id=materia_id, docente_id=docente_id,
            ).first()
            if not monte:
                senza_monte += 1
                logger.warning(
                    f"No monte ore row for classe {classe_id} / materia {materia_id} / "
                    f"docente {docente_id}: {n}h not scaled"
                )
                continue
            monte.ore_erogate = (monte.ore_erogate or 0) + n
            ore_scalate += n
            aggiornate += 1
        return {
            "ore_scalate": ore_scalate,
            "assegnazioni_aggiornate": aggiornate,
            "senza_monte_ore": senza_monte,
        }

    def approve_schedule(self, scuola_id: str, week_start: date) -> Dict[str, Any]:
        """
        Approve schedule (change from BOZZA to APPROVATO) and lock it from
        further modifications.

        Approving is also the moment the week's hours are "delivered": every
        lesson of the week is added to ore_erogate of its own assegnazione
        (docente + classe + materia), so the residual (ore_totali -
        ore_erogate) that the next weeks' targets are built on goes down.
        Each classe of a joint (accoppiata) lesson receives it, so both
        sides' assegnazioni are scaled. Hours that were not held (an absence,
        a cancelled lesson) are simply not scaled, so the next weeks'
        residual spreads them over the remaining weeks.
        Idempotent: approving an already approved week scales nothing again.
        """
        logger.info(f"Approving schedule for school {scuola_id} week {week_start}")

        try:
            schedule = self.repo.get_schedule_by_week(scuola_id, week_start)

            if not schedule:
                return {
                    "status": "error",
                    "message": "No schedule found for this week",
                }

            from datetime import datetime
            from app.models import OrarioSettimanale, AuditLog

            orario = self.db.query(OrarioSettimanale).filter(
                OrarioSettimanale.scuola_id == scuola_id,
                OrarioSettimanale.settimana_inizio == week_start,
            ).first()

            if not orario:
                return {
                    "status": "error",
                    "message": "Schedule not found in DB",
                }

            if orario.stato == "APPROVATO":
                # already approved (and its hours already scaled): nothing to do
                return {
                    "status": "approved",
                    "schedule_id": orario.id,
                    "stato": "APPROVATO",
                    "ore_scalate": 0,
                    "assegnazioni_aggiornate": 0,
                    "senza_monte_ore": 0,
                    "message": "Orario già approvato: le ore erano già state scalate.",
                }

            old_stato = orario.stato
            orario.stato = "APPROVATO"
            orario.approved_at = datetime.utcnow()

            scaled = self.scale_monte_ore(scuola_id, orario)
            ore_scalate = scaled["ore_scalate"]
            aggiornate = scaled["assegnazioni_aggiornate"]
            senza_monte = scaled["senza_monte_ore"]

            self.db.add(AuditLog(
                scuola_id=scuola_id,
                orario_settimanale_id=orario.id,
                azione="SCHEDULE_APPROVED",
                dettagli={
                    "da": old_stato, "a": "APPROVATO", "ore_scalate": ore_scalate,
                    "assegnazioni_aggiornate": aggiornate, "senza_monte_ore": senza_monte,
                },
            ))
            self.db.commit()

            logger.info(f"Schedule approved: {orario.id}, {ore_scalate}h scaled on {aggiornate} assegnazioni")

            return {
                "status": "approved",
                "schedule_id": orario.id,
                "stato": "APPROVATO",
                "ore_scalate": ore_scalate,
                "assegnazioni_aggiornate": aggiornate,
                "senza_monte_ore": senza_monte,
            }

        except Exception as e:
            logger.error(f"Error approving schedule: {e}")
            self.db.rollback()
            return {
                "status": "error",
                "message": str(e),
            }

    def get_quality_score(self, scuola_id: str, week_start: date) -> Optional[Dict[str, Any]]:
        """
        Return the quality score stored for this week's schedule (computed
        at generation/modification time from the solver's soft constraints).
        Returns None if no schedule exists for this week.
        """
        schedule = self.repo.get_schedule_by_week(scuola_id, week_start)
        if not schedule:
            return None

        return {
            "quality_score": schedule["quality_score"],
            "quality_level": schedule["quality_level"],
            "details": {
                "n_soft_conflicts": schedule["n_soft_conflicts"],
                "total_slots": len(schedule["slots"]),
                "stato": schedule["stato"],
            },
        }

    def modify_slot(
        self, scuola_id: str, week_start: date, slot_id: str, changes: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Move a single slot to a different docente/giorno/ora_inizio, then
        recheck every hard constraint and recompute the quality score by
        re-solving the same CP-SAT model with every variable pinned to the
        resulting full-week assignment (see ScheduleSolver.solve_fixed).
        """
        from app.models import OrarioSettimanale, SlotLezione, AuditLog, ConflittoGestito
        from app.domain.solver import ScheduleSolver, GiornoEnum

        orario = self.db.query(OrarioSettimanale).filter(
            OrarioSettimanale.scuola_id == scuola_id,
            OrarioSettimanale.settimana_inizio == week_start,
        ).first()
        if not orario:
            return {"status": "error", "message": "No schedule found for this week"}
        if orario.stato == "APPROVATO":
            return {"status": "error", "message": "Schedule is approved and locked from modifications"}

        slot = self.db.query(SlotLezione).filter(
            SlotLezione.id == slot_id,
            SlotLezione.orario_settimanale_id == orario.id,
        ).first()
        if not slot:
            return {"status": "error", "message": "Slot not found in this schedule"}

        new_docente_id = changes.get("docente_id", slot.docente_id)
        new_giorno = changes.get("giorno", slot.giorno)
        try:
            new_ora_inizio = int(changes.get("ora_inizio", slot.ora_inizio))
        except (TypeError, ValueError):
            return {"status": "error", "message": f"Invalid ora_inizio: {changes.get('ora_inizio')!r}"}

        if new_giorno not in GiornoEnum.__members__:
            return {"status": "error", "message": f"Invalid giorno: {new_giorno!r}"}
        if not (8 <= new_ora_inizio <= 13):
            return {"status": "error", "message": f"Invalid ora_inizio: {new_ora_inizio} (must be 8-13)"}

        context = self.repo.get_week_context(scuola_id, week_start)

        if new_giorno != slot.giorno:
            after = sum(
                1 for s in orario.slot_lezioni
                if s.classe_id == slot.classe_id and s.giorno == new_giorno
            ) + 1
            reason = self._day_max_violation(context, slot.classe_id, new_giorno, after)
            if reason:
                return {"status": "error", "message": reason}

        # Decision variables are keyed by assegnazione_id, so moving the
        # slot to a different docente is only possible if that docente is
        # already linked to this classe/materia via an Assegnazione.
        target_asg = next(
            (a for a in context.assegnazioni
             if a.classe_id == slot.classe_id and a.materia_id == slot.materia_id
             and a.docente_id == new_docente_id),
            None,
        )
        if not target_asg:
            return {
                "status": "error",
                "message": "This teacher has no assignment for this class/subject; cannot move the slot there.",
            }

        # Rebuild the proposed full-week assignment: every other currently
        # committed slot, unchanged, plus this one at its new docente/giorno/ora.
        assigned_keys = set()
        for s in orario.slot_lezioni:
            if s.id == slot.id:
                continue
            asg = next(
                (a for a in context.assegnazioni
                 if a.classe_id == s.classe_id and a.materia_id == s.materia_id
                 and a.docente_id == s.docente_id),
                None,
            )
            if asg:
                assigned_keys.add((asg.assegnazione_id, GiornoEnum[s.giorno].value, s.ora_inizio - 8))
        assigned_keys.add((target_asg.assegnazione_id, GiornoEnum[new_giorno].value, new_ora_inizio - 8))

        solver, status, _ = self._solve_with_fallback(context, fixed_keys=assigned_keys)

        if status not in ("OPTIMAL", "FEASIBLE"):
            return {
                "status": "error",
                "message": "This modification breaks a scheduling rule (double booking, "
                           "paired class, availability, or daily hour limit).",
            }

        quality_score, quality_level, n_conflicts = solver.calculate_quality_score()

        slot.docente_id = new_docente_id
        slot.giorno = new_giorno
        slot.ora_inizio = new_ora_inizio
        slot.ora_fine = new_ora_inizio + 1

        orario.quality_score = quality_score
        orario.quality_level = quality_level
        orario.n_conflitti_soft = n_conflicts

        audit = AuditLog(
            scuola_id=scuola_id,
            orario_settimanale_id=orario.id,
            azione="MODIFY_SLOT",
            dettagli={"slot_id": slot_id, "changes": changes},
        )
        self.db.add(audit)
        self.db.commit()

        updated = self.repo.get_schedule_by_week(scuola_id, week_start)
        conflicts = self._apply_handled(orario.id, solver.get_conflicts())
        self._mark_slot_conflicts(updated["slots"], conflicts)
        self._mark_slot_unavailability(updated["slots"], scuola_id, week_start)
        return {"status": "modified", "conflicts": conflicts, **updated}

    def apply_quick_action(
        self,
        scuola_id: str,
        week_start: date,
        action_type: str,
        class_id: Optional[str] = None,
        teacher_id: Optional[str] = None,
        giorno: Optional[str] = None,
        max_hours: Optional[int] = None,
        timeout_seconds: int = 60,
    ) -> Dict[str, Any]:
        """
        Apply a "deroga" (temporary exemption from one soft/hard rule) for
        this week and re-solve, replacing the current schedule's slots in
        place (same schedule_id) with the result.
        """
        from app.domain.solver import DerogaConfig, GiornoEnum

        if action_type not in QUICK_ACTIONS:
            return {"status": "error", "message": f"Unknown quick action: {action_type!r}"}

        if giorno is not None and giorno not in GiornoEnum.__members__:
            return {"status": "error", "message": f"Invalid giorno: {giorno!r}"}
        giorno_idx = GiornoEnum[giorno].value if giorno is not None else None

        deroga = DerogaConfig(
            action_type=action_type, classe_id=class_id, docente_id=teacher_id,
            giorno=giorno_idx, max_hours=max_hours,
        )
        return self._regenerate_in_place(
            scuola_id, week_start,
            azione="QUICK_ACTION",
            dettagli={
                "action_type": action_type, "class_id": class_id, "teacher_id": teacher_id,
                "giorno": giorno, "max_hours": max_hours,
            },
            timeout_seconds=timeout_seconds,
            deroga=deroga,
        )

    def exclude_docente_day(
        self, scuola_id: str, week_start: date, docente_id: str, giorno: str,
    ) -> Dict[str, Any]:
        """AI chat "escludi [docente] [giorno]": zero out a docente's hours for one giorno this week."""
        from app.domain.solver import GiornoEnum

        if giorno not in GiornoEnum.__members__:
            return {"status": "error", "message": f"Invalid giorno: {giorno!r}"}

        return self._regenerate_in_place(
            scuola_id, week_start,
            azione="CHAT_EXCLUDE_DAY",
            dettagli={"docente_id": docente_id, "giorno": giorno},
            exclude_docente_giorno={(docente_id, GiornoEnum[giorno].value)},
        )

    def cap_docente_weekly_hours(
        self, scuola_id: str, week_start: date, docente_id: str, max_hours: int,
    ) -> Dict[str, Any]:
        """AI chat "riduci ore [docente] a massimo N": hard weekly-hours cap for this week."""
        return self._regenerate_in_place(
            scuola_id, week_start,
            azione="CHAT_REDUCE_WORKLOAD",
            dettagli={"docente_id": docente_id, "max_hours": max_hours},
            max_hours_per_docente={docente_id: max_hours},
        )

    def set_max_consecutive_teoria(
        self, scuola_id: str, week_start: date, max_hours: int,
    ) -> Dict[str, Any]:
        """AI chat "imposta massimo N ore consecutive di teoria" for this week."""
        return self._regenerate_in_place(
            scuola_id, week_start,
            azione="CHAT_SET_SOFT_CONSTRAINT",
            dettagli={"constraint_type": "consecutive_hours", "max_hours": max_hours},
            max_consecutive_teoria=max_hours,
        )

    def move_lesson(
        self, scuola_id: str, week_start: date, classe_id: str, materia_id: str,
        from_giorno: str, to_giorno: str,
    ) -> Dict[str, Any]:
        """
        AI chat "sposta [materia] [classe] da [giorno] a [giorno]": move
        every slot for this classe/materia on from_giorno to to_giorno
        (same ora_inizio), through modify_slot so it's validated and
        rescored exactly like a manual drag-and-drop edit.
        """
        from app.models import OrarioSettimanale, SlotLezione

        orario = self.db.query(OrarioSettimanale).filter(
            OrarioSettimanale.scuola_id == scuola_id,
            OrarioSettimanale.settimana_inizio == week_start,
        ).first()
        if not orario:
            return {"status": "error", "message": "No schedule found for this week"}

        matching = self.db.query(SlotLezione).filter(
            SlotLezione.orario_settimanale_id == orario.id,
            SlotLezione.classe_id == classe_id,
            SlotLezione.materia_id == materia_id,
            SlotLezione.giorno == from_giorno,
        ).all()
        if not matching:
            return {"status": "error", "message": "No matching lesson found on that day"}

        result = None
        for slot in matching:
            result = self.modify_slot(scuola_id, week_start, slot.id, {"giorno": to_giorno})
            if result["status"] != "modified":
                return result  # bail on first failure, its message explains why
        return result

    def _regenerate_in_place(
        self,
        scuola_id: str,
        week_start: date,
        *,
        azione: str,
        dettagli: Dict[str, Any],
        success_status: str = "applied",
        timeout_seconds: int = 60,
        **solver_kwargs,
    ) -> Dict[str, Any]:
        """
        Shared machinery behind apply_quick_action and the AI chat's
        exclude-day/reduce-workload/soft-constraint intents: re-solve the
        full week with extra solver_kwargs (a DerogaConfig relaxation, or
        one of the chat's hard-constraint additions - see
        ScheduleSolver.__init__), then replace this week's slots in place
        (same schedule_id).
        """
        from app.models import OrarioSettimanale, SlotLezione, AuditLog, ConflittoGestito
        from app.domain.solver import ScheduleSolver

        orario = self.db.query(OrarioSettimanale).filter(
            OrarioSettimanale.scuola_id == scuola_id,
            OrarioSettimanale.settimana_inizio == week_start,
        ).first()
        if not orario:
            return {"status": "error", "message": "No schedule found for this week"}
        if orario.stato == "APPROVATO":
            return {"status": "error", "message": "Schedule is approved and locked from modifications"}

        context = self.repo.get_week_context(scuola_id, week_start)
        if not context.assegnazioni:
            return {"status": "error", "message": "No teacher-class-subject assignments found."}

        solver, status, _ = self._solve_with_fallback(
            context, timeout_seconds=timeout_seconds, **solver_kwargs,
        )

        if status not in ("OPTIMAL", "FEASIBLE"):
            return {
                "status": "error",
                "message": "No feasible schedule found with this change applied.",
            }

        slots = solver.extract_solution()
        quality_score, quality_level, n_conflicts = solver.calculate_quality_score()

        try:
            self.db.query(SlotLezione).filter(
                SlotLezione.orario_settimanale_id == orario.id
            ).delete(synchronize_session=False)
            # a new solution: earlier approve/reject decisions no longer apply
            self.db.query(ConflittoGestito).filter(
                ConflittoGestito.orario_settimanale_id == orario.id
            ).delete(synchronize_session=False)

            for slot in slots:
                self.db.add(SlotLezione(
                    orario_settimanale_id=orario.id,
                    classe_id=slot["classe_id"],
                    docente_id=slot["docente_id"],
                    materia_id=slot["materia_id"],
                    giorno=slot["giorno"],
                    ora_inizio=slot["ora_inizio"],
                    ora_fine=slot["ora_fine"],
                    accoppiata=slot.get("accoppiata", False),
                    classe_accoppiata_id=slot.get("classe_accoppiata_id"),
                ))

            orario.quality_score = quality_score
            orario.quality_level = quality_level
            orario.n_conflitti_soft = n_conflicts

            audit = AuditLog(
                scuola_id=scuola_id,
                orario_settimanale_id=orario.id,
                azione=azione,
                dettagli=dettagli,
            )
            self.db.add(audit)
            self.db.commit()

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error regenerating schedule ({azione}): {e}")
            return {"status": "error", "message": str(e)}

        updated = self.repo.get_schedule_by_week(scuola_id, week_start)
        conflicts = solver.get_conflicts()
        self._mark_slot_conflicts(updated["slots"], conflicts)
        self._mark_slot_unavailability(updated["slots"], scuola_id, week_start)
        return {"status": success_status, "conflicts": conflicts, **updated}

    def export_pdf(self, scuola_id: str, week_start: date) -> Dict[str, Any]:
        """
        Return metadata + a download URL for the week's PDF tabellone. The
        PDF itself is rendered on demand by the download route (see
        render_pdf) rather than written to disk here, so it's always built
        from the current schedule state (no stale-file cache to invalidate).
        """
        logger.info(f"Exporting schedule to PDF: school {scuola_id} week {week_start}")

        schedule = self.repo.get_schedule_by_week(scuola_id, week_start)
        if not schedule:
            return {"status": "error", "message": "No schedule found for this week"}

        return {
            "status": "generated",
            "filename": f"orario_{week_start}.pdf",
            "pdf_url": f"/api/schedule/{week_start}/export-pdf/file",
        }

    def export_excel(self, scuola_id: str, week_start: date) -> Dict[str, Any]:
        """Return metadata + a download URL for the week's .xlsx tabellone."""
        logger.info(f"Exporting schedule to Excel: school {scuola_id} week {week_start}")

        schedule = self.repo.get_schedule_by_week(scuola_id, week_start)
        if not schedule:
            return {"status": "error", "message": "No schedule found for this week"}

        return {
            "status": "generated",
            "filename": f"orario_{week_start}.xlsx",
            "xlsx_url": f"/api/schedule/{week_start}/export-excel/file",
        }

    def render_pdf(self, scuola_id: str, week_start: date) -> Optional[bytes]:
        """
        Render the weekly tabellone (classi x ore, one landscape page per
        giorno, per specs.md 6.3) as a PDF via WeasyPrint. Returns None if
        no schedule exists for this week.
        """
        schedule = self.repo.get_schedule_by_week(scuola_id, week_start)
        if not schedule:
            return None

        from weasyprint import HTML

        html = self._render_tabellone_html(schedule)
        return HTML(string=html).write_pdf()

    def render_excel(self, scuola_id: str, week_start: date) -> Optional[bytes]:
        """
        Render the weekly tabellone as an .xlsx workbook with the same single-
        sheet structure as the PDF (see _render_tabellone_html and
        Documenti/es_di_calendario.pdf): title banner, red header, one block
        per giorno with a vertical day label, docente surname only, per-classe
        colors. Returns None if no schedule exists for this week.
        """
        schedule = self.repo.get_schedule_by_week(scuola_id, week_start)
        if not schedule:
            return None

        from io import BytesIO
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.utils import get_column_letter

        slots = schedule["slots"]
        stage_cells_list = schedule.get("stage_cells") or []

        classi = {}
        for s in slots:
            classi.setdefault(s["classe_id"], s.get("classe_nome") or s["classe_id"])
        for sc in stage_cells_list:
            classi.setdefault(sc["classe_id"], sc.get("classe_nome") or sc["classe_id"])
        classi_sorted = sorted(classi.items(), key=lambda c: self._tab_sort_key(c[1]))

        by_cell = {(s["giorno"], s["ora_inizio"], s["classe_id"]): s for s in slots}
        stage_set = {(sc["classe_id"], sc["giorno"]) for sc in stage_cells_list}

        def fill(hex_color: str) -> PatternFill:
            return PatternFill("solid", fgColor=hex_color.lstrip("#").upper())

        thin = Side(style="thin", color="000000")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)
        center = Alignment(horizontal="center", vertical="center")
        n_cols = len(classi_sorted) + 2

        wb = Workbook()
        ws = wb.active
        ws.title = "Orario"

        titolo = self._tab_titolo_settimana(week_start)
        for r, (text, size) in enumerate(
            [("Agenzia Formativa don Angelo Tedoldi", 16), (f"Orario scolastico {titolo}", 16)], start=1
        ):
            ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=n_cols)
            c = ws.cell(row=r, column=1, value=text)
            c.font = Font(bold=True, size=size)
            c.alignment = center
            c.fill = fill("#95b3d7")
            ws.row_dimensions[r].height = 24

        header_row = 3
        for j, label in enumerate(["DATA", "Orario"] + [n for _, n in classi_sorted], start=1):
            c = ws.cell(row=header_row, column=j, value=label)
            c.font = Font(bold=True, color="FFFFFF", size=9)
            c.fill = fill("#c00000")
            c.alignment = center
            c.border = border
        ws.column_dimensions["A"].width = 6
        ws.column_dimensions["B"].width = 8
        for j in range(3, n_cols + 1):
            ws.column_dimensions[get_column_letter(j)].width = 15
        ws.freeze_panes = ws.cell(row=header_row + 1, column=3)

        row = header_row + 1
        for idx, (giorno, label) in enumerate(self._GIORNI_LABELS.items()):
            # Drop trailing hours nobody has (e.g. a short Friday), like the sheet.
            ore_con_lezioni = [
                o for o in self._ORE
                if any((giorno, o, cid) in by_cell for cid, _ in classi_sorted)
            ]
            last = max(ore_con_lezioni, default=self._ORE[-1])
            ore = [o for o in self._ORE if o <= last]

            start = row
            for ora in ore:
                c = ws.cell(row=row, column=2, value=f"{ora}-{ora + 1}")
                c.alignment = center
                c.border = border
                c.font = Font(size=8)
                for j, (cid, nome) in enumerate(classi_sorted, start=3):
                    if (cid, giorno) in stage_set:
                        c = ws.cell(row=row, column=j, value="STAGE")
                        c.fill = fill("#ffff00")
                        c.font = Font(bold=True, color="000000")
                    else:
                        slot = by_cell.get((giorno, ora, cid))
                        if slot:
                            doc = slot.get("docente_nome") or slot["docente_id"]
                            c = ws.cell(row=row, column=j, value=doc.split()[0] if doc else "")
                            c.font = Font(bold=True)
                            k = self._tab_classe_key(nome)
                            colore = self._TAB_COLORI.get((k[1], k[0])) if k else None
                            if colore:
                                c.fill = fill(colore)
                        else:
                            c = ws.cell(row=row, column=j)
                            c.fill = fill("#d9d9d9")
                    c.alignment = center
                    c.border = border
                row += 1

            ws.merge_cells(start_row=start, start_column=1, end_row=row - 1, end_column=1)
            c = ws.cell(row=start, column=1, value=label.lower())
            c.fill = fill("#e46c0a" if idx % 2 == 0 else "#0070c0")
            c.font = Font(italic=True, color="FFFFFF", size=9)
            c.alignment = Alignment(horizontal="center", vertical="center", text_rotation=90)
            for r in range(start, row):
                ws.cell(row=r, column=1).border = border

            if idx < len(self._GIORNI_LABELS) - 1:
                for j in range(1, n_cols + 1):
                    ws.cell(row=row, column=j).fill = fill("#d9d9d9")
                ws.row_dimensions[row].height = 6
                row += 1

        ws.page_setup.orientation = "landscape"
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True

        buf = BytesIO()
        wb.save(buf)
        return buf.getvalue()

    _GIORNI_LABELS = {
        "LUNEDI": "Lunedì", "MARTEDI": "Martedì", "MERCOLEDI": "Mercoledì",
        "GIOVEDI": "Giovedì", "VENERDI": "Venerdì",
    }
    _ORE = range(8, 14)

    @staticmethod
    def _group_classi_for_hour(cell_slots: Dict[str, Dict[str, Any]]) -> Dict[str, List[str]]:
        """
        Union classi that share one joint lesson this hour, following each
        slot's classe_accoppiata_id edge. A joint lesson can span more than
        2 classi (see ClasseAccoppiata's docstring: a 4-way group is stored
        as one row per pair), so any single classe's own edge only names
        one partner - the full group is the transitive closure of every
        edge present this hour, not just one skipped partner.
        Returns classe_id -> full group (including itself), for every
        classe_id in cell_slots.
        """
        parent = {c: c for c in cell_slots}

        def find(x: str) -> str:
            while parent[x] != x:
                x = parent[x]
            return x

        for classe_id, slot in cell_slots.items():
            partner = slot.get("classe_accoppiata_id")
            if slot.get("accoppiata") and partner in parent:
                ra, rb = find(classe_id), find(partner)
                if ra != rb:
                    parent[ra] = rb

        groups: Dict[str, List[str]] = {}
        for classe_id in cell_slots:
            groups.setdefault(find(classe_id), []).append(classe_id)

        return {classe_id: groups[find(classe_id)] for classe_id in cell_slots}

    # --- Tabellone PDF: layout modeled on Documenti/es_di_calendario.pdf ---
    _TAB_INDIRIZZI = ["OP. INFORM.", "ELETTRICISTI", "ESTETISTE", "PAN. E PAST", "I.T.C."]
    _TAB_ROMANI = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
    _TAB_MESI = [
        "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio",
        "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
    ]
    # Fill per (indirizzo, anno) as in the reference sheet; anything else is white.
    _TAB_COLORI = {
        ("OP. INFORM.", 1): "#ddd9c4", ("OP. INFORM.", 2): "#f2dcdb", ("OP. INFORM.", 3): "#92d050",
        ("ELETTRICISTI", 1): "#ddd9c4", ("ELETTRICISTI", 2): "#f2dcdb", ("ELETTRICISTI", 3): "#ff99cc",
        ("ESTETISTE", 1): "#c5d9f1", ("ESTETISTE", 2): "#fde9d9", ("ESTETISTE", 3): "#ff99cc",
        ("PAN. E PAST", 1): "#c5d9f1", ("PAN. E PAST", 2): "#fde9d9", ("PAN. E PAST", 3): "#92d050",
        ("I.T.C.", 1): "#ffff99",
    }

    @classmethod
    def _tab_classe_key(cls, nome: str):
        """(anno, indirizzo) parsed from e.g. 'III PAN. E PAST.'; None if unparseable."""
        parts = (nome or "").strip().upper().split(" ", 1)
        if len(parts) == 2 and parts[0] in cls._TAB_ROMANI:
            rest = parts[1].strip().rstrip(".")
            for ind in cls._TAB_INDIRIZZI:
                if rest == ind.rstrip("."):
                    return cls._TAB_ROMANI[parts[0]], ind
        return None

    @classmethod
    def _tab_sort_key(cls, nome: str):
        k = cls._tab_classe_key(nome)
        if k is None:
            return (len(cls._TAB_INDIRIZZI), 0, nome)
        anno, ind = k
        return (cls._TAB_INDIRIZZI.index(ind), anno, nome)

    @classmethod
    def _tab_titolo_settimana(cls, week_start: date) -> str:
        fine = week_start + timedelta(days=4)
        if week_start.month == fine.month:
            return f"dal {week_start.day} al {fine.day} {cls._TAB_MESI[fine.month - 1]}"
        return (
            f"dal {week_start.day} {cls._TAB_MESI[week_start.month - 1]} "
            f"al {fine.day} {cls._TAB_MESI[fine.month - 1]}"
        )

    def _render_tabellone_html(self, schedule: Dict[str, Any]) -> str:
        """
        Single A4-landscape page: all five days stacked, one column per classe,
        one row per hour, docente surname only - same structure as the school's
        reference sheet. Every cell is the real slot of that giorno/ora/classe,
        so teachers vary across days exactly as in the schedule.
        """
        from html import escape

        ws = schedule["week_start"]
        if isinstance(ws, str):
            ws = date.fromisoformat(ws)

        slots = schedule["slots"]
        stage_cells_list = schedule.get("stage_cells") or []

        classi = {}
        for s in slots:
            classi.setdefault(s["classe_id"], s.get("classe_nome") or s["classe_id"])
        for sc in stage_cells_list:
            classi.setdefault(sc["classe_id"], sc.get("classe_nome") or sc["classe_id"])
        classi_sorted = sorted(classi.items(), key=lambda c: self._tab_sort_key(c[1]))

        by_cell = {(s["giorno"], s["ora_inizio"], s["classe_id"]): s for s in slots}
        stage_set = {(sc["classe_id"], sc["giorno"]) for sc in stage_cells_list}

        def colore(nome: str) -> str:
            k = self._tab_classe_key(nome)
            if k is None:
                return "#ffffff"
            return self._TAB_COLORI.get((k[1], k[0]), "#ffffff")

        colors = {cid: colore(nome) for cid, nome in classi_sorted}

        body = []
        for idx, giorno in enumerate(self._GIORNI_LABELS):
            # Drop trailing hours nobody has (e.g. a short Friday), like the sheet.
            ore = [
                o for o in self._ORE
                if any((giorno, o, cid) in by_cell for cid, _ in classi_sorted)
            ]
            if not ore:
                ore = list(self._ORE)
            last = max(
                (o for o in ore),
                default=self._ORE[-1],
            )
            ore = [o for o in self._ORE if o <= last]

            label_cls = "g-orange" if idx % 2 == 0 else "g-blue"
            label = self._GIORNI_LABELS[giorno].lower()
            for i, ora in enumerate(ore):
                cells = []
                if i == 0:
                    cells.append(
                        f'<td class="giorno {label_cls}" rowspan="{len(ore)}">'
                        f'<div class="giorno-txt">{escape(label)}</div></td>'
                    )
                cells.append(f'<td class="ora">{ora}-{ora + 1}</td>')
                for cid, _ in classi_sorted:
                    if (cid, giorno) in stage_set:
                        cells.append('<td class="stage">STAGE</td>')
                        continue
                    slot = by_cell.get((giorno, ora, cid))
                    if not slot:
                        cells.append('<td class="vuota"></td>')
                        continue
                    nome = slot.get("docente_nome") or slot["docente_id"]
                    cognome = escape(nome.split()[0]) if nome else ""
                    cells.append(f'<td style="background:{colors[cid]}">{cognome}</td>')
                body.append(f"<tr>{''.join(cells)}</tr>")
            if idx < len(self._GIORNI_LABELS) - 1:
                body.append(f'<tr class="sep"><td colspan="{len(classi_sorted) + 2}"></td></tr>')

        header = "".join(f"<th>{escape(nome)}</th>" for _, nome in classi_sorted)
        n = max(len(classi_sorted), 1)
        colgroup = '<col style="width:3.5%"><col style="width:3.5%">' + (
            f'<col style="width:{93 / n:.3f}%">' * n
        )
        titolo = self._tab_titolo_settimana(ws)

        return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page {{ size: A4 landscape; margin: 8mm; }}
  body {{ font-family: Calibri, Carlito, Helvetica, Arial, sans-serif; margin: 0; color: #000; }}
  .banner {{ background: #95b3d7; text-align: center; font-weight: bold; padding: 2mm 0; margin-bottom: 1mm; }}
  .banner .t1 {{ font-size: 14pt; }}
  .banner .t2 {{ font-size: 14pt; }}
  table {{ width: 100%; table-layout: fixed; border-collapse: collapse; }}
  th {{ background: #c00000; color: #fff; font-size: 4.8pt; font-weight: bold;
        border: 0.6pt solid #000; padding: 0.4mm 0; text-align: center; white-space: nowrap; }}
  td {{ border: 0.5pt solid #000; font-size: 5.8pt; font-weight: bold; text-align: center;
        padding: 0.35mm 0; overflow: hidden; white-space: nowrap; }}
  td.ora {{ font-weight: normal; font-size: 4.6pt; }}
  td.vuota {{ background: #d9d9d9; }}
  td.stage {{ background: #ffff00; color: #000; }}
  td.giorno {{ width: 3.5%; padding: 0; vertical-align: middle; }}
  td.g-orange {{ background: #e46c0a; }}
  td.g-blue {{ background: #0070c0; }}
  .giorno-txt {{ color: #fff; font-size: 6pt; font-style: italic; white-space: nowrap;
                 transform: rotate(-90deg); display: inline-block; }}
  tr.sep td {{ background: #d9d9d9; border: none; height: 1.6mm; padding: 0; }}
</style>
</head>
<body>
  <div class="banner"><div class="t1">Agenzia Formativa don Angelo Tedoldi</div>
  <div class="t2">Orario scolastico {escape(titolo)}</div></div>
  <table>
    <colgroup>{colgroup}</colgroup>
    <thead><tr><th>DATA</th><th>Orario</th>{header}</tr></thead>
    <tbody>{''.join(body)}</tbody>
  </table>
</body>
</html>"""
