from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any, Dict, List
from app.database import get_db
from app.security import require_admin_for_writes
from app.services.dati import SchoolDataService
import logging

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_admin_for_writes)])


def _get_current_school_id() -> str:
    """TODO: Get from auth context."""
    return "sch_1"


def _not_found_or_bad_request(e: ValueError) -> HTTPException:
    status_code = 404 if "not found" in str(e) else 400
    return HTTPException(status_code=status_code, detail=str(e))


# ===== Classi =====

@router.get("/classes")
def list_classes(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    try:
        return SchoolDataService(db).list_classi(_get_current_school_id())
    except Exception as e:
        logger.error(f"Error listing classes: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/classes")
def create_class(data: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return SchoolDataService(db).create_classe(_get_current_school_id(), data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating class: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/classes/{classe_id}")
def update_class(classe_id: str, data: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return SchoolDataService(db).update_classe(_get_current_school_id(), classe_id, data)
    except ValueError as e:
        raise _not_found_or_bad_request(e)
    except Exception as e:
        logger.error(f"Error updating class: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/classes/{classe_id}")
def delete_class(classe_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        SchoolDataService(db).delete_classe(_get_current_school_id(), classe_id)
        return {"status": "deleted", "classe_id": classe_id}
    except ValueError as e:
        raise _not_found_or_bad_request(e)
    except Exception as e:
        logger.error(f"Error deleting class: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===== Materie =====

@router.get("/subjects")
def list_subjects(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    try:
        return SchoolDataService(db).list_materie(_get_current_school_id())
    except Exception as e:
        logger.error(f"Error listing subjects: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/subjects")
def create_subject(data: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return SchoolDataService(db).create_materia(_get_current_school_id(), data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating subject: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/subjects/{materia_id}")
def update_subject(materia_id: str, data: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return SchoolDataService(db).update_materia(_get_current_school_id(), materia_id, data)
    except ValueError as e:
        raise _not_found_or_bad_request(e)
    except Exception as e:
        logger.error(f"Error updating subject: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/subjects/{materia_id}")
def delete_subject(materia_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        SchoolDataService(db).delete_materia(_get_current_school_id(), materia_id)
        return {"status": "deleted", "materia_id": materia_id}
    except ValueError as e:
        raise _not_found_or_bad_request(e)
    except Exception as e:
        logger.error(f"Error deleting subject: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===== Assegnazioni (+ monte ore) =====

@router.get("/assignments")
def list_assignments(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    try:
        return SchoolDataService(db).list_assegnazioni(_get_current_school_id())
    except Exception as e:
        logger.error(f"Error listing assignments: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/assignments")
def create_assignment(data: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return SchoolDataService(db).create_assegnazione(_get_current_school_id(), data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating assignment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/assignments/{assignment_id}")
def update_assignment(assignment_id: str, data: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return SchoolDataService(db).update_assegnazione(_get_current_school_id(), assignment_id, data)
    except ValueError as e:
        raise _not_found_or_bad_request(e)
    except Exception as e:
        logger.error(f"Error updating assignment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/assignments/{assignment_id}")
def delete_assignment(assignment_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        SchoolDataService(db).delete_assegnazione(_get_current_school_id(), assignment_id)
        return {"status": "deleted", "assignment_id": assignment_id}
    except ValueError as e:
        raise _not_found_or_bad_request(e)
    except Exception as e:
        logger.error(f"Error deleting assignment: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===== Accoppiamenti =====

@router.get("/class-pairings")
def list_class_pairings(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    try:
        return SchoolDataService(db).list_accoppiamenti(_get_current_school_id())
    except Exception as e:
        logger.error(f"Error listing class pairings: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/class-pairings")
def create_class_pairing(data: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return SchoolDataService(db).create_accoppiamento(_get_current_school_id(), data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating class pairing: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/class-pairings/{pairing_id}")
def update_class_pairing(pairing_id: str, data: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return SchoolDataService(db).update_accoppiamento(_get_current_school_id(), pairing_id, data)
    except ValueError as e:
        raise _not_found_or_bad_request(e)
    except Exception as e:
        logger.error(f"Error updating class pairing: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/class-pairings/{pairing_id}")
def delete_class_pairing(pairing_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        SchoolDataService(db).delete_accoppiamento(_get_current_school_id(), pairing_id)
        return {"status": "deleted", "pairing_id": pairing_id}
    except ValueError as e:
        raise _not_found_or_bad_request(e)
    except Exception as e:
        logger.error(f"Error deleting class pairing: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ===== Calendario =====

@router.get("/calendar")
def list_calendar(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    try:
        return SchoolDataService(db).list_calendario(_get_current_school_id())
    except Exception as e:
        logger.error(f"Error listing calendar: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/calendar")
def create_calendar_entry(data: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return SchoolDataService(db).create_calendario(_get_current_school_id(), data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error creating calendar entry: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("/calendar/{date_id}")
def update_calendar_entry(date_id: str, data: Dict[str, Any], db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        return SchoolDataService(db).update_calendario(_get_current_school_id(), date_id, data)
    except ValueError as e:
        raise _not_found_or_bad_request(e)
    except Exception as e:
        logger.error(f"Error updating calendar entry: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/calendar/{date_id}")
def delete_calendar_entry(date_id: str, db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        SchoolDataService(db).delete_calendario(_get_current_school_id(), date_id)
        return {"status": "deleted", "date_id": date_id}
    except ValueError as e:
        raise _not_found_or_bad_request(e)
    except Exception as e:
        logger.error(f"Error deleting calendar entry: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
