from sqlalchemy.orm import Session
from datetime import date
from typing import Dict, Any, Optional
from app.repositories.schedule import ScheduleRepository
from app.domain.solver import ScheduleSolver
from app.schemas import ScheduleGenerateResponse, SlotLezioneResponse
import logging

logger = logging.getLogger(__name__)

QUICK_ACTIONS = {
    "force_3_hours_theory",
    "reduce_contract_hours",
    "authorize_early_exit",
    "override_availability",
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
            # 1. Extract context from DB
            context = self.repo.get_week_context(scuola_id, week_start)

            if not context.assegnazioni:
                logger.warning("No assegnazioni found for this school")
                return ScheduleGenerateResponse(
                    status="error",
                    message="No teacher-class-subject assignments found. Setup incomplete.",
                )

            # 2. Build and solve model
            solver = ScheduleSolver(context)
            solver.build_model()
            status = solver.solve(timeout_seconds=timeout_seconds)

            # 3. Handle results
            if status in ["OPTIMAL", "FEASIBLE"]:
                # Extract solution
                slots = solver.extract_solution()

                # Calculate quality
                quality_score, quality_level, n_conflicts = solver.calculate_quality_score()

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
                        docente_id=s["docente_id"],
                        materia_id=s["materia_id"],
                        giorno=s["giorno"],
                        ora_inizio=s["ora_inizio"],
                        ora_fine=s["ora_fine"],
                        accoppiata=s["accoppiata"],
                        classe_accoppiata_id=s.get("classe_accoppiata_id"),
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

    def get_schedule(self, scuola_id: str, week_start: date) -> Dict[str, Any]:
        """
        Retrieve previously generated schedule.
        """
        logger.info(f"Retrieving schedule for school {scuola_id} week {week_start}")

        try:
            schedule = self.repo.get_schedule_by_week(scuola_id, week_start)

            if not schedule:
                return {
                    "status": "not_found",
                    "message": "No schedule found for this week",
                }

            return {
                "status": "found",
                "schedule": schedule,
            }

        except Exception as e:
            logger.error(f"Error retrieving schedule: {e}")
            return {
                "status": "error",
                "message": str(e),
            }

    # ===== Helper Methods =====

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

    def approve_schedule(self, scuola_id: str, week_start: date) -> Dict[str, Any]:
        """
        Approve schedule (change from BOZZA to APPROVATO).
        Lock from further modifications.
        """
        logger.info(f"Approving schedule for school {scuola_id} week {week_start}")

        try:
            schedule = self.repo.get_schedule_by_week(scuola_id, week_start)

            if not schedule:
                return {
                    "status": "error",
                    "message": "No schedule found for this week",
                }

            # Update stato to APPROVATO
            from app.models import OrarioSettimanale, AuditLog

            orario = self.db.query(OrarioSettimanale).filter(
                OrarioSettimanale.scuola_id == scuola_id,
                OrarioSettimanale.settimana_inizio == week_start,
            ).first()

            if orario:
                old_stato = orario.stato
                orario.stato = "APPROVATO"
                self.db.commit()

                # Audit log
                audit = AuditLog(
                    scuola_id=scuola_id,
                    azione=f"SCHEDULE_APPROVED",
                    dettagli=f"Changed from {old_stato} to APPROVATO",
                )
                self.db.add(audit)
                self.db.commit()

                logger.info(f"Schedule approved: {orario.id}")

                return {
                    "status": "approved",
                    "schedule_id": orario.id,
                    "stato": "APPROVATO",
                }

            return {
                "status": "error",
                "message": "Schedule not found in DB",
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
        from app.models import OrarioSettimanale, SlotLezione, AuditLog
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

        solver = ScheduleSolver(context)
        solver.build_model()
        status = solver.solve_fixed(assigned_keys)

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
        return {"status": "modified", **updated}

    def apply_quick_action(
        self,
        scuola_id: str,
        week_start: date,
        action_type: str,
        class_id: Optional[str] = None,
        teacher_id: Optional[str] = None,
        timeout_seconds: int = 60,
    ) -> Dict[str, Any]:
        """
        Apply a "deroga" (temporary exemption from one soft/hard rule) for
        this week and re-solve, replacing the current schedule's slots in
        place (same schedule_id) with the result.
        """
        from app.models import OrarioSettimanale, SlotLezione, AuditLog
        from app.domain.solver import ScheduleSolver, DerogaConfig

        if action_type not in QUICK_ACTIONS:
            return {"status": "error", "message": f"Unknown quick action: {action_type!r}"}

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

        deroga = DerogaConfig(action_type=action_type, classe_id=class_id, docente_id=teacher_id)
        solver = ScheduleSolver(context, deroga=deroga)
        solver.build_model()
        status = solver.solve(timeout_seconds=timeout_seconds)

        if status not in ("OPTIMAL", "FEASIBLE"):
            return {
                "status": "error",
                "message": "No feasible schedule found even with this exemption applied.",
            }

        slots = solver.extract_solution()
        quality_score, quality_level, n_conflicts = solver.calculate_quality_score()

        try:
            self.db.query(SlotLezione).filter(
                SlotLezione.orario_settimanale_id == orario.id
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
                azione="QUICK_ACTION",
                dettagli={"action_type": action_type, "class_id": class_id, "teacher_id": teacher_id},
            )
            self.db.add(audit)
            self.db.commit()

        except Exception as e:
            self.db.rollback()
            logger.error(f"Error applying quick action: {e}")
            return {"status": "error", "message": str(e)}

        updated = self.repo.get_schedule_by_week(scuola_id, week_start)
        return {"status": "applied", **updated}

    def export_pdf(self, scuola_id: str, week_start: date) -> Dict[str, Any]:
        """
        Export schedule to PDF tabellone.
        TODO: Implement WeasyPrint rendering for actual PDF generation.
        """
        logger.info(f"Exporting schedule to PDF: school {scuola_id} week {week_start}")

        try:
            schedule = self.repo.get_schedule_by_week(scuola_id, week_start)

            if not schedule:
                return {
                    "status": "error",
                    "message": "No schedule found for this week",
                }

            # TODO: Generate PDF using WeasyPrint
            # For now, return placeholder

            return {
                "status": "generated",
                "filename": f"orario_{week_start}.pdf",
                "message": "PDF export not yet implemented (WeasyPrint integration pending)",
            }

        except Exception as e:
            logger.error(f"Error exporting PDF: {e}")
            return {
                "status": "error",
                "message": str(e),
            }
