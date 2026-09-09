from sqlalchemy.orm import Session
from sqlalchemy import and_
from datetime import date, timedelta
from app.models import DisponibilitaSettimanale, Docente
from app.schemas import AvailabilityResponse
from typing import Optional, Dict, List, Any


class AvailabilityRepository:
    """Repository for availability operations."""

    def __init__(self, db: Session):
        self.db = db

    def get_availability(
        self, scuola_id: str, teacher_id: str, week_start: date
    ) -> Optional[DisponibilitaSettimanale]:
        """Get availability record for teacher in week."""
        return self.db.query(DisponibilitaSettimanale).filter(
            and_(
                DisponibilitaSettimanale.scuola_id == scuola_id,
                DisponibilitaSettimanale.docente_id == teacher_id,
                DisponibilitaSettimanale.settimana_inizio == week_start,
            )
        ).first()

    def get_previous_week_availability(
        self, scuola_id: str, teacher_id: str, week_start: date
    ) -> Optional[DisponibilitaSettimanale]:
        """Get availability from previous week."""
        prev_week = week_start - timedelta(days=7)
        return self.get_availability(scuola_id, teacher_id, prev_week)

    def create_or_update_availability(
        self,
        scuola_id: str,
        teacher_id: str,
        week_start: date,
        giorni_fasce: Dict[str, List[Dict[str, Any]]],
    ) -> DisponibilitaSettimanale:
        """Create or update availability record."""
        availability = self.get_availability(scuola_id, teacher_id, week_start)

        if availability:
            # Update
            availability.giorni_fasce = giorni_fasce
            self.db.commit()
        else:
            # Create new
            availability = DisponibilitaSettimanale(
                scuola_id=scuola_id,
                docente_id=teacher_id,
                settimana_inizio=week_start,
                giorni_fasce=giorni_fasce,
            )
            self.db.add(availability)
            self.db.commit()

        return availability

    def get_all_teachers_availability(
        self, scuola_id: str, week_start: date
    ) -> List[DisponibilitaSettimanale]:
        """Get all teachers' availability for week."""
        return self.db.query(DisponibilitaSettimanale).filter(
            and_(
                DisponibilitaSettimanale.scuola_id == scuola_id,
                DisponibilitaSettimanale.settimana_inizio == week_start,
            )
        ).all()

    def copy_week_availability(
        self, scuola_id: str, from_week: date, to_week: date
    ) -> int:
        """Copy availability from one week to another."""
        from_records = self.db.query(DisponibilitaSettimanale).filter(
            and_(
                DisponibilitaSettimanale.scuola_id == scuola_id,
                DisponibilitaSettimanale.settimana_inizio == from_week,
            )
        ).all()

        copied_count = 0
        for record in from_records:
            # Check if target week already exists
            existing = self.db.query(DisponibilitaSettimanale).filter(
                and_(
                    DisponibilitaSettimanale.scuola_id == scuola_id,
                    DisponibilitaSettimanale.docente_id == record.docente_id,
                    DisponibilitaSettimanale.settimana_inizio == to_week,
                )
            ).first()

            if not existing:
                new_record = DisponibilitaSettimanale(
                    scuola_id=scuola_id,
                    docente_id=record.docente_id,
                    settimana_inizio=to_week,
                    giorni_fasce=record.giorni_fasce,
                )
                self.db.add(new_record)
                copied_count += 1

        self.db.commit()
        return copied_count

    def mark_teacher_not_first_time(self, scuola_id: str, teacher_id: str) -> None:
        """Mark teacher as not first time this year."""
        teacher = self.db.query(Docente).filter(
            and_(Docente.scuola_id == scuola_id, Docente.id == teacher_id)
        ).first()

        if teacher:
            teacher.first_time_this_year = False
            self.db.commit()
