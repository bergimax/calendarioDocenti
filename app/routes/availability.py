from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import date
from typing import List, Dict, Any
from app.database import get_db
from app.models import Docente
from app.repositories.availability import AvailabilityRepository
from app.schemas import AvailabilityResponse, AvailabilitySaveRequest

router = APIRouter()


def _get_current_school_id() -> str:
    """
    TODO: Get school_id from auth context.
    For now, return dummy value.
    """
    return "sch_1"


@router.get("/availability/{week_start}/{teacher_id}")
def get_availability(
    week_start: date,
    teacher_id: str,
    db: Session = Depends(get_db),
) -> AvailabilityResponse:
    """
    Get teacher availability for specific week.
    If no record exists:
    - New teacher: return default grid (8-14 all days)
    - Recurring teacher: inherit from previous week
    """
    scuola_id = _get_current_school_id()

    repo = AvailabilityRepository(db)

    # 1. Try to get existing record
    availability = repo.get_availability(scuola_id, teacher_id, week_start)

    if availability:
        return AvailabilityResponse(
            teacher_id=teacher_id,
            week_start=week_start,
            giorni_fasce=availability.giorni_fasce,
        )

    # 2. Check if teacher is first-time
    teacher = db.query(Docente).filter_by(id=teacher_id).first()
    if not teacher:
        raise HTTPException(status_code=404, detail="Teacher not found")

    if teacher.first_time_this_year:
        # Return default grid (8-14, all days available)
        default_grid = _generate_default_availability_grid()
        return AvailabilityResponse(
            teacher_id=teacher_id,
            week_start=week_start,
            giorni_fasce=default_grid,
            is_default=True,
        )

    # 3. Try to inherit from previous week
    prev_availability = repo.get_previous_week_availability(scuola_id, teacher_id, week_start)

    if prev_availability:
        return AvailabilityResponse(
            teacher_id=teacher_id,
            week_start=week_start,
            giorni_fasce=prev_availability.giorni_fasce,
            is_inherited=True,
        )

    # 4. Fallback to default
    default_grid = _generate_default_availability_grid()
    return AvailabilityResponse(
        teacher_id=teacher_id,
        week_start=week_start,
        giorni_fasce=default_grid,
        is_default=True,
    )


@router.post("/availability/{week_start}/{teacher_id}")
def save_availability(
    week_start: date,
    teacher_id: str,
    request: AvailabilitySaveRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Save teacher availability for week.
    Creates new record or updates existing.
    Marks teacher as "not first_time_this_year".
    """
    scuola_id = _get_current_school_id()

    try:
        repo = AvailabilityRepository(db)

        # Validate request
        if not request.giorni_fasce:
            raise HTTPException(status_code=400, detail="Empty availability grid")

        # Save availability
        availability = repo.create_or_update_availability(
            scuola_id=scuola_id,
            teacher_id=teacher_id,
            week_start=week_start,
            giorni_fasce=request.giorni_fasce,
        )

        # Mark teacher as not first-time
        repo.mark_teacher_not_first_time(scuola_id, teacher_id)

        return {
            "status": "saved",
            "teacher_id": teacher_id,
            "week_start": week_start,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/availability/{week_start}/copy-from/{prev_week}")
def copy_availability_from_previous_week(
    week_start: date,
    prev_week: date,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Copy all teachers' availability from previous week to current week.
    """
    scuola_id = _get_current_school_id()

    try:
        repo = AvailabilityRepository(db)

        copied_count = repo.copy_week_availability(
            scuola_id=scuola_id,
            from_week=prev_week,
            to_week=week_start,
        )

        return {
            "status": "copied",
            "teachers_copied": copied_count,
            "from_week": prev_week,
            "to_week": week_start,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/availability/{week_start}/status")
def check_availability_status(
    week_start: date,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Check if all teachers have availability filled for week.
    """
    scuola_id = _get_current_school_id()

    try:
        repo = AvailabilityRepository(db)

        # Get all active teachers
        all_teachers = db.query(Docente).filter_by(
            scuola_id=scuola_id,
            active=True,
        ).all()

        # Get teachers with availability for this week
        availability_records = repo.get_all_teachers_availability(scuola_id, week_start)
        teachers_with_availability = {a.docente_id for a in availability_records}

        total_teachers = len(all_teachers)
        filled_teachers = len(teachers_with_availability)
        ready_to_generate = filled_teachers == total_teachers

        return {
            "week_complete": ready_to_generate,
            "total_teachers": total_teachers,
            "teachers_with_availability": filled_teachers,
            "ready_to_generate": ready_to_generate,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _generate_default_availability_grid() -> Dict[str, List[Dict[str, Any]]]:
    """Generate default availability grid (8-14, all days available)."""
    days = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi"]
    grid = {}

    for day in days:
        slots = []
        for hour in range(8, 14):
            slots.append({
                "ora_inizio": f"{hour:02d}:00",
                "ora_fine": f"{hour+1:02d}:00",
                "disponibile": True,
            })
        grid[day] = slots

    return grid
