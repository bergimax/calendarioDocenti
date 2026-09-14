from sqlalchemy.orm import Session
from datetime import date, timedelta
from typing import Dict, List, Any, Optional
from app.models import DisponibilitaSettimanale, Docente
from app.repositories.availability import AvailabilityRepository
from app.schemas import AvailabilityResponse
import logging

logger = logging.getLogger(__name__)


class AvailabilityService:
    """Business logic for teacher availability management."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = AvailabilityRepository(db)

    def get_or_create_availability(
        self, scuola_id: str, teacher_id: str, week_start: date
    ) -> AvailabilityResponse:
        """
        Get teacher availability for week.
        Strategy:
        1. Check if record exists
        2. If not and new teacher: return default (8-14)
        3. If not and recurring: inherit from previous week
        4. Fallback to default
        """
        # 1. Try to get existing record
        existing = self.repo.get_availability(scuola_id, teacher_id, week_start)
        if existing:
            logger.info(
                f"Availability found for teacher {teacher_id} week {week_start}"
            )
            return AvailabilityResponse(
                teacher_id=teacher_id,
                week_start=week_start,
                giorni_fasce=existing.giorni_fasce,
            )

        # 2. Check if teacher exists
        teacher = self.db.query(Docente).filter_by(
            scuola_id=scuola_id, id=teacher_id
        ).first()

        if not teacher:
            logger.error(f"Teacher {teacher_id} not found in school {scuola_id}")
            raise ValueError(f"Teacher {teacher_id} not found")

        # 3. Check if first-time teacher
        if teacher.first_time_this_year:
            logger.info(f"Teacher {teacher_id} is first-time. Returning default grid.")
            default_grid = self._generate_default_grid()
            return AvailabilityResponse(
                teacher_id=teacher_id,
                week_start=week_start,
                giorni_fasce=default_grid,
                is_default=True,
            )

        # 4. Try to inherit from previous week
        prev_week = week_start - timedelta(days=7)
        prev_availability = self.repo.get_availability(
            scuola_id, teacher_id, prev_week
        )

        if prev_availability:
            logger.info(
                f"Teacher {teacher_id} inheriting availability from previous week"
            )
            return AvailabilityResponse(
                teacher_id=teacher_id,
                week_start=week_start,
                giorni_fasce=prev_availability.giorni_fasce,
                is_inherited=True,
            )

        # 5. Fallback to default
        logger.info(
            f"Teacher {teacher_id} has no previous availability. Using default grid."
        )
        default_grid = self._generate_default_grid()
        return AvailabilityResponse(
            teacher_id=teacher_id,
            week_start=week_start,
            giorni_fasce=default_grid,
            is_default=True,
        )

    def save_availability(
        self,
        scuola_id: str,
        teacher_id: str,
        week_start: date,
        giorni_fasce: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """
        Save teacher availability for week.
        Validates input, saves to DB, marks teacher as "not first time".
        """
        # 1. Validate input
        if not giorni_fasce:
            raise ValueError("Availability grid cannot be empty")

        self._validate_giorni_fasce_format(giorni_fasce)

        # 2. Save availability
        try:
            availability = self.repo.create_or_update_availability(
                scuola_id=scuola_id,
                teacher_id=teacher_id,
                week_start=week_start,
                giorni_fasce=giorni_fasce,
            )

            logger.info(
                f"Availability saved for teacher {teacher_id} week {week_start}"
            )

            # 3. Mark teacher as not first-time
            self.repo.mark_teacher_not_first_time(scuola_id, teacher_id)

            return {
                "status": "saved",
                "teacher_id": teacher_id,
                "week_start": str(week_start),
                "availability_id": availability.id,
            }

        except Exception as e:
            logger.error(f"Error saving availability: {e}")
            raise

    def copy_week_availability(
        self, scuola_id: str, from_week: date, to_week: date
    ) -> Dict[str, Any]:
        """
        Copy all teachers' availability from one week to another.
        Skips teachers who already have availability in target week.
        """
        # 1. Validate weeks
        if from_week >= to_week:
            raise ValueError("from_week must be before to_week")

        # 2. Copy availability
        try:
            copied_count = self.repo.copy_week_availability(
                scuola_id=scuola_id, from_week=from_week, to_week=to_week
            )

            logger.info(
                f"Copied availability from {from_week} to {to_week}: {copied_count} teachers"
            )

            return {
                "status": "copied",
                "teachers_copied": copied_count,
                "from_week": str(from_week),
                "to_week": str(to_week),
            }

        except Exception as e:
            logger.error(f"Error copying availability: {e}")
            raise

    def check_week_status(self, scuola_id: str, week_start: date) -> Dict[str, Any]:
        """
        Check if all teachers have availability filled for week.
        Returns count of teachers with/without availability.
        """
        # 1. Get all active teachers
        all_teachers = self.db.query(Docente).filter_by(
            scuola_id=scuola_id, active=True
        ).all()

        # 2. Get teachers with availability this week
        availability_records = self.repo.get_all_teachers_availability(
            scuola_id, week_start
        )
        teachers_with_availability = {a.docente_id for a in availability_records}

        # 3. Calculate status
        total_teachers = len(all_teachers)
        filled_teachers = len(teachers_with_availability)
        ready_to_generate = filled_teachers == total_teachers

        logger.info(
            f"Week {week_start} availability status: {filled_teachers}/{total_teachers} teachers"
        )

        return {
            "week_complete": ready_to_generate,
            "total_teachers": total_teachers,
            "teachers_with_availability": filled_teachers,
            "teachers_missing": total_teachers - filled_teachers,
            "ready_to_generate": ready_to_generate,
            "completion_percentage": (filled_teachers / total_teachers * 100) if total_teachers > 0 else 0,
        }

    def list_teachers(self, scuola_id: str) -> List[Dict[str, Any]]:
        """Active teachers for this scuola, for the availability page's teacher grid."""
        docenti = self.db.query(Docente).filter_by(scuola_id=scuola_id, active=True).order_by(Docente.nome).all()
        return [
            {"teacher_id": d.id, "nome": d.nome, "email": d.email or "", "tipo": d.tipo}
            for d in docenti
        ]

    def create_teacher(self, scuola_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a docente for the "Dati scuola" management page."""
        nome = (data.get("nome") or "").strip()
        if not nome:
            raise ValueError("nome is required")
        tipo = (data.get("tipo") or "ASSUNTO").strip().upper()
        if tipo not in ("ASSUNTO", "CONTRATTO"):
            raise ValueError(f"tipo must be ASSUNTO or CONTRATTO, got {tipo!r}")

        docente = Docente(
            scuola_id=scuola_id,
            nome=nome,
            email=(data.get("email") or "").strip() or None,
            tipo=tipo,
        )
        self.db.add(docente)
        self.db.commit()
        return {"teacher_id": docente.id, "nome": docente.nome, "email": docente.email or "", "tipo": docente.tipo}

    def update_teacher(self, scuola_id: str, teacher_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        docente = self.db.query(Docente).filter_by(id=teacher_id, scuola_id=scuola_id).first()
        if not docente:
            raise ValueError(f"Teacher {teacher_id!r} not found")

        if "nome" in data and data["nome"]:
            docente.nome = data["nome"].strip()
        if "email" in data:
            docente.email = (data["email"] or "").strip() or None
        if "tipo" in data and data["tipo"]:
            tipo = data["tipo"].strip().upper()
            if tipo not in ("ASSUNTO", "CONTRATTO"):
                raise ValueError(f"tipo must be ASSUNTO or CONTRATTO, got {tipo!r}")
            docente.tipo = tipo

        self.db.commit()
        return {"teacher_id": docente.id, "nome": docente.nome, "email": docente.email or "", "tipo": docente.tipo}

    def delete_teacher(self, scuola_id: str, teacher_id: str) -> None:
        from sqlalchemy.exc import IntegrityError

        docente = self.db.query(Docente).filter_by(id=teacher_id, scuola_id=scuola_id).first()
        if not docente:
            raise ValueError(f"Teacher {teacher_id!r} not found")
        try:
            self.db.delete(docente)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ValueError("Cannot delete: this teacher has related assignments, availability, or schedule slots")

    def list_weeks(self, scuola_id: str) -> List[Dict[str, Any]]:
        """
        Every Monday-starting school week within this scuola's anno
        formativo (data_inizio_anno..data_fine_anno), for the week
        selector on the availability and orario pages.
        """
        from app.models import Scuola

        scuola = self.db.query(Scuola).filter_by(id=scuola_id).first()
        if not scuola:
            return []

        # First Monday on/after data_inizio_anno.
        current = scuola.data_inizio_anno + timedelta(days=(7 - scuola.data_inizio_anno.weekday()) % 7)

        weeks = []
        week_num = 1
        while current <= scuola.data_fine_anno:
            weeks.append({
                "start": current.isoformat(),
                "end": (current + timedelta(days=4)).isoformat(),
                "week_num": week_num,
            })
            current += timedelta(days=7)
            week_num += 1

        return weeks

    # ===== Helper Methods =====

    def _generate_default_grid(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Generate default availability grid.
        8-14 (08:00-09:00, 09:00-10:00, ..., 13:00-14:00)
        All days available.
        """
        days = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi"]
        grid = {}

        for day in days:
            slots = []
            for hour in range(8, 14):  # 8-9, 9-10, ..., 13-14
                slots.append({
                    "ora_inizio": f"{hour:02d}:00",
                    "ora_fine": f"{hour + 1:02d}:00",
                    "disponibile": True,
                })
            grid[day] = slots

        return grid

    def _validate_giorni_fasce_format(
        self, giorni_fasce: Dict[str, List[Dict[str, Any]]]
    ) -> None:
        """
        Validate format of giorni_fasce.
        Must have: lunedi-venerdi, each with list of hour slots.
        Each slot must have: ora_inizio, ora_fine, disponibile.
        """
        required_days = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi"]

        # Check all days present
        if not all(day in giorni_fasce for day in required_days):
            missing = [d for d in required_days if d not in giorni_fasce]
            raise ValueError(f"Missing days in availability: {missing}")

        # Check each day's slots
        for day, slots in giorni_fasce.items():
            if not isinstance(slots, list):
                raise ValueError(f"Day {day} must contain list of slots")

            if len(slots) == 0:
                raise ValueError(f"Day {day} has no slots")

            for idx, slot in enumerate(slots):
                # Check required fields
                required_fields = ["ora_inizio", "ora_fine", "disponibile"]
                if not all(field in slot for field in required_fields):
                    missing = [f for f in required_fields if f not in slot]
                    raise ValueError(
                        f"Slot {idx} in {day} missing fields: {missing}"
                    )

                # Validate time format
                try:
                    ora_inizio = slot["ora_inizio"]
                    ora_fine = slot["ora_fine"]

                    # Parse time (HH:MM format)
                    inizio_parts = ora_inizio.split(":")
                    fine_parts = ora_fine.split(":")

                    if len(inizio_parts) != 2 or len(fine_parts) != 2:
                        raise ValueError("Time must be in HH:MM format")

                    inizio_hour = int(inizio_parts[0])
                    fine_hour = int(fine_parts[0])

                    # Validate range (8-14)
                    if not (8 <= inizio_hour < 14 and 8 < fine_hour <= 14):
                        raise ValueError(
                            f"Time must be between 08:00 and 14:00 (slot: {ora_inizio}-{ora_fine})"
                        )

                    # Validate fine > inizio
                    if fine_hour <= inizio_hour:
                        raise ValueError(
                            f"End time must be after start time ({ora_inizio}-{ora_fine})"
                        )

                except (ValueError, TypeError) as e:
                    raise ValueError(f"Invalid time in slot {idx} ({day}): {e}")

                # Validate disponibile is boolean
                if not isinstance(slot["disponibile"], bool):
                    raise ValueError(
                        f"disponibile must be boolean in slot {idx} ({day})"
                    )

        logger.info("Giorni_fasce format validation passed")
