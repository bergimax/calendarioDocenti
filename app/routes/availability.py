from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from datetime import date
from typing import Dict, Any, List
from app.database import get_db
from app.security import get_current_admin, require_admin
from app.services.availability import AvailabilityService
from app.schemas import AvailabilityResponse, AvailabilitySaveRequest
import logging

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(get_current_admin)])


def _get_current_school_id() -> str:
    """
    TODO: Get school_id from auth context.
    For now, return dummy value.
    """
    return "sch_1"


@router.get("/teachers")
def list_teachers(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """Active teachers for the current scuola, for the availability page's teacher grid."""
    scuola_id = _get_current_school_id()

    try:
        service = AvailabilityService(db)
        return service.list_teachers(scuola_id)

    except Exception as e:
        logger.error(f"Error listing teachers: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/teachers", dependencies=[Depends(require_admin)])
def create_teacher(data: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Create a docente ("Dati scuola" management page)."""
    scuola_id = _get_current_school_id()
    try:
        return AvailabilityService(db).create_teacher(scuola_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating teacher: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/teachers/{teacher_id}", dependencies=[Depends(require_admin)])
def update_teacher(teacher_id: str, data: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    scuola_id = _get_current_school_id()
    try:
        return AvailabilityService(db).update_teacher(scuola_id, teacher_id, data)
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e) else 400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating teacher: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/teachers/{teacher_id}", dependencies=[Depends(require_admin)])
def delete_teacher(teacher_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    scuola_id = _get_current_school_id()
    try:
        AvailabilityService(db).delete_teacher(scuola_id, teacher_id)
        return {"status": "deleted", "teacher_id": teacher_id}
    except ValueError as e:
        raise HTTPException(status_code=404 if "not found" in str(e) else 400, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting teacher: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/availability/weeks")
def list_weeks(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """
    Every school week (Monday-starting) for the current scuola, for the
    week selector on the availability and orario pages.
    """
    scuola_id = _get_current_school_id()

    try:
        service = AvailabilityService(db)
        return {"weeks": service.list_weeks(scuola_id)}

    except Exception as e:
        logger.error(f"Error listing weeks: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/availability/{week_start}/status")
def check_availability_status(
    week_start: date,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Check if all teachers have availability filled for week.
    Returns status and counts.

    NOTE: this route must stay registered before
    GET /availability/{week_start}/{teacher_id}, otherwise FastAPI would match
    "status" as a teacher_id and this endpoint would be unreachable.
    """
    scuola_id = _get_current_school_id()

    try:
        service = AvailabilityService(db)
        result = service.check_week_status(
            scuola_id=scuola_id,
            week_start=week_start,
        )
        return result

    except Exception as e:
        logger.error(f"Error checking availability status: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/availability/{week_start}/{teacher_id}")
def get_availability(
    week_start: date,
    teacher_id: str,
    db: Session = Depends(get_db),
) -> AvailabilityResponse:
    """
    Get teacher availability for specific week.
    Strategy:
    1. If exists: return
    2. If new teacher: return default grid (8-14 all days)
    3. If recurring: inherit from previous week
    4. Else: return default grid
    """
    scuola_id = _get_current_school_id()

    try:
        service = AvailabilityService(db)
        availability = service.get_or_create_availability(
            scuola_id=scuola_id,
            teacher_id=teacher_id,
            week_start=week_start,
        )
        return availability

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error retrieving availability: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/availability/{week_start}/{teacher_id}")
def save_availability(
    week_start: date,
    teacher_id: str,
    request: AvailabilitySaveRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Save teacher availability for week.
    - Creates new record or updates existing
    - Marks teacher as "not first_time_this_year"
    - Validates giorni_fasce format
    """
    scuola_id = _get_current_school_id()

    try:
        service = AvailabilityService(db)
        result = service.save_availability(
            scuola_id=scuola_id,
            teacher_id=teacher_id,
            week_start=week_start,
            giorni_fasce=request.giorni_fasce,
        )
        return result

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error saving availability: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/availability/{week_start}/copy-from/{prev_week}")
def copy_availability_from_previous_week(
    week_start: date,
    prev_week: date,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Copy all teachers' availability from previous week to current week.
    Skips teachers who already have availability in target week.
    """
    scuola_id = _get_current_school_id()

    try:
        service = AvailabilityService(db)
        result = service.copy_week_availability(
            scuola_id=scuola_id,
            from_week=prev_week,
            to_week=week_start,
        )
        return result

    except ValueError as e:
        logger.warning(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error copying availability: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
