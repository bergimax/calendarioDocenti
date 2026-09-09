from sqlalchemy.orm import Session
from datetime import date
from typing import Dict, Any, Optional
from app.repositories.schedule import ScheduleRepository
from app.domain.solver import ScheduleSolver
from app.schemas import ScheduleGenerateResponse, SlotLezioneResponse
import logging

logger = logging.getLogger(__name__)


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
