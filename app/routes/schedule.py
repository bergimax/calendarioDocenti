from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session
from datetime import date
from typing import Dict, Any
from app.database import get_db
from app.security import get_current_admin
from app.services.schedule import ScheduleService
from app.services.feedback import FeedbackService, UnknownMotivo
from app.models import Admin
from app.schemas import ScheduleGenerateRequest, ScheduleGenerateResponse, ModifySlotRequest, QuickActionRequest, ApproveConflictRequest, RejectConflictRequest, AssignSlotRequest, ScheduleFeedbackRequest
import logging

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(get_current_admin)])


def _get_current_school_id() -> str:
    """TODO: Get from auth context."""
    return "sch_1"


@router.post("/schedule/generate")
def generate_schedule(
    request: ScheduleGenerateRequest,
    db: Session = Depends(get_db),
) -> ScheduleGenerateResponse:
    """
    Generate optimal schedule for week using OR-Tools solver.
    """
    scuola_id = _get_current_school_id()

    try:
        service = ScheduleService(db)
        result = service.generate_schedule(
            scuola_id=scuola_id,
            week_start=request.week_start,
            timeout_seconds=60,
        )
        return result

    except Exception as e:
        logger.error(f"Error generating schedule: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/schedule/{week_start}/regenerate")
def regenerate_schedule(
    week_start: date,
    db: Session = Depends(get_db),
) -> ScheduleGenerateResponse:
    """
    Regenerate schedule for week from scratch (replaces the week's slots
    in place; same underlying flow as /schedule/generate).
    """
    scuola_id = _get_current_school_id()

    try:
        service = ScheduleService(db)
        return service.generate_schedule(
            scuola_id=scuola_id,
            week_start=week_start,
            timeout_seconds=60,
        )

    except Exception as e:
        logger.error(f"Error regenerating schedule: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/schedule/{week_start}")
def get_schedule(
    week_start: date,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Retrieve schedule for week.
    """
    scuola_id = _get_current_school_id()

    try:
        service = ScheduleService(db)
        result = service.get_schedule(
            scuola_id=scuola_id,
            week_start=week_start,
        )

        if result is None:
            raise HTTPException(status_code=404, detail="No schedule found for this week")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving schedule: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/schedule/{week_start}/quality-score")
def get_quality_score(
    week_start: date,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Get quality score details for schedule.
    """
    scuola_id = _get_current_school_id()

    try:
        service = ScheduleService(db)
        result = service.get_quality_score(scuola_id=scuola_id, week_start=week_start)

        if result is None:
            raise HTTPException(status_code=404, detail="No schedule found for this week")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting quality score: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/schedule/{week_start}/modify-slot")
def modify_slot(
    week_start: date,
    request: ModifySlotRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Modify single schedule slot and recalculate quality score.
    """
    scuola_id = _get_current_school_id()

    try:
        service = ScheduleService(db)
        return service.modify_slot(
            scuola_id=scuola_id,
            week_start=week_start,
            slot_id=request.slot_id,
            changes=request.changes,
        )

    except Exception as e:
        logger.error(f"Error modifying slot: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schedule/{week_start}/assignable/{classe_id}")
def assignable_for_classe(
    week_start: date,
    classe_id: str,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Docente/materia pairs that can be assigned to a free hour of this classe."""
    try:
        return {"options": ScheduleService(db).assignable_for_classe(
            _get_current_school_id(), week_start, classe_id,
        )}
    except Exception as e:
        logger.error(f"Error listing assignable teachers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/schedule/{week_start}/assign-slot")
def assign_slot(
    week_start: date,
    request: AssignSlotRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Manually assign a lesson to a free hour. Returns the updated schedule."""
    try:
        return ScheduleService(db).assign_slot(
            _get_current_school_id(), week_start, request.classe_id, request.giorno.value,
            request.ora_inizio, request.docente_id, request.materia_id,
        )
    except Exception as e:
        logger.error(f"Error assigning slot: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/schedule/{week_start}/conflicts/approve")
def approve_conflicts(
    week_start: date,
    request: ApproveConflictRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Approve conflicts: they stop being reported. Returns the updated schedule."""
    try:
        return ScheduleService(db).approve_conflicts(
            _get_current_school_id(), week_start, request.chiavi,
        )
    except Exception as e:
        logger.error(f"Error approving conflicts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/schedule/{week_start}/conflicts/reject")
def reject_conflict(
    week_start: date,
    request: RejectConflictRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Reject: remove the lesson at classe/giorno/ora and leave the hour free. Returns the updated schedule."""
    try:
        return ScheduleService(db).reject_conflict(
            _get_current_school_id(), week_start,
            request.classe_id, request.giorno.value, request.ora_inizio,
        )
    except Exception as e:
        logger.error(f"Error rejecting conflict: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/schedule/{week_start}/apply-quick-action")
def apply_quick_action(
    week_start: date,
    request: QuickActionRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Apply quick action (deroga) and recalculate.
    """
    scuola_id = _get_current_school_id()

    try:
        service = ScheduleService(db)
        return service.apply_quick_action(
            scuola_id=scuola_id,
            week_start=week_start,
            action_type=request.action_type,
            class_id=request.class_id,
            teacher_id=request.teacher_id,
            giorno=request.giorno,
            max_hours=request.max_hours,
        )

    except Exception as e:
        logger.error(f"Error applying quick action: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/schedule/{week_start}/approve")
def approve_schedule(
    week_start: date,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Approve schedule (change from BOZZA to APPROVATO).
    Lock from modifications.
    """
    scuola_id = _get_current_school_id()

    try:
        service = ScheduleService(db)
        result = service.approve_schedule(
            scuola_id=scuola_id,
            week_start=week_start,
        )
        return result

    except Exception as e:
        logger.error(f"Error approving schedule: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schedule/{week_start}/export-pdf")
def export_pdf(
    week_start: date,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Export schedule to PDF tabellone.
    """
    scuola_id = _get_current_school_id()

    try:
        service = ScheduleService(db)
        result = service.export_pdf(
            scuola_id=scuola_id,
            week_start=week_start,
        )
        return result

    except Exception as e:
        logger.error(f"Error exporting PDF: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schedule/{week_start}/export-pdf/file")
def download_pdf(
    week_start: date,
    db: Session = Depends(get_db),
) -> Response:
    """
    Stream the actual PDF tabellone bytes (the URL returned by export-pdf).
    """
    scuola_id = _get_current_school_id()

    try:
        service = ScheduleService(db)
        pdf_bytes = service.render_pdf(scuola_id=scuola_id, week_start=week_start)

        if pdf_bytes is None:
            raise HTTPException(status_code=404, detail="No schedule found for this week")

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="orario_{week_start}.pdf"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rendering PDF: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/schedule/{week_start}/export-excel")
def export_excel(
    week_start: date,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Export schedule to Excel tabellone.
    """
    scuola_id = _get_current_school_id()

    try:
        service = ScheduleService(db)
        result = service.export_excel(
            scuola_id=scuola_id,
            week_start=week_start,
        )
        return result

    except Exception as e:
        logger.error(f"Error exporting Excel: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/schedule/{week_start}/export-excel/file")
def download_excel(
    week_start: date,
    db: Session = Depends(get_db),
) -> Response:
    """
    Stream the actual .xlsx tabellone bytes (the URL returned by export-excel).
    """
    scuola_id = _get_current_school_id()

    try:
        service = ScheduleService(db)
        xlsx_bytes = service.render_excel(scuola_id=scuola_id, week_start=week_start)

        if xlsx_bytes is None:
            raise HTTPException(status_code=404, detail="No schedule found for this week")

        return Response(
            content=xlsx_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="orario_{week_start}.xlsx"'},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rendering Excel: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/schedule/{week_start}/feedback")
def get_schedule_feedback(
    week_start: date,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Ratings the admin gave to this week's schedule (newest first) and the selectable reasons."""
    result = FeedbackService(db).get(_get_current_school_id(), week_start)
    if result is None:
        raise HTTPException(status_code=404, detail="No schedule found for this week")
    return result


@router.post("/schedule/{week_start}/feedback")
def add_schedule_feedback(
    week_start: date,
    request: ScheduleFeedbackRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Rate the week's schedule (1-5) with the reasons it went wrong. Append-only."""
    try:
        saved = FeedbackService(db).add(
            _get_current_school_id(), week_start,
            voto=request.voto, motivi=request.motivi, nota=request.nota,
            admin_id=admin.id,
        )
    except UnknownMotivo as e:
        raise HTTPException(status_code=422, detail=str(e))
    if saved is None:
        raise HTTPException(status_code=404, detail="No schedule found for this week")
    return saved
