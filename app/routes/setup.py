from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session
from datetime import date
from typing import Dict, Any, Optional
from app.database import get_db
from app.security import get_current_admin
from app.services.setup import SetupService
from app.schemas import (
    FileUploadResponse,
    SetupValidationResponse,
    FieldValidationRequest,
    FieldValidationResponse,
    CorrectionRequest,
    SetupSaveRequest,
    SetupSaveResponse,
)
import logging

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(get_current_admin)])

# Single service instance holding the in-progress setup wizard state.
# v1 is single-tenant/admin-only (one setup flow at a time), so a module-level
# singleton is used instead of a dict keyed by id(db): that id is a memory
# address which Python can and does reuse once a previous Session is garbage
# collected, so two unrelated requests could otherwise share cached data.
_setup_service: Optional[SetupService] = None


def _get_current_school_id() -> str:
    """TODO: Get from auth context."""
    return "sch_1"


def _get_setup_service(db: Session) -> SetupService:
    """Get or create the SetupService for the in-progress setup flow."""
    global _setup_service
    if _setup_service is None:
        _setup_service = SetupService(db)
    else:
        _setup_service.db = db
        _setup_service.repo.db = db
    return _setup_service


async def _upload_and_ingest(
    file_type: str,
    id_prefix: str,
    allowed_extensions: tuple,
    file: UploadFile,
    db: Session,
) -> FileUploadResponse:
    """
    Shared logic for every /api/*/upload endpoint: read the file, parse it
    via SetupService.ingest_file (caching the result for the setup wizard so
    a later POST /api/setup/validate doesn't need to repeat this field in its
    JSON body - the frontend only sends back the file_ids), and wrap the
    result as a FileUploadResponse.
    """
    filename = file.filename or ""
    if not filename.lower().endswith(allowed_extensions):
        raise HTTPException(
            status_code=400,
            detail=f"{file_type} file must be one of: {', '.join(allowed_extensions)}",
        )

    content = await file.read()

    try:
        service = _get_setup_service(db)
        result = service.ingest_file(file_type, filename, content)
    except ValueError as e:
        logger.warning(f"{file_type} upload validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"{file_type} upload parse error: {e}")
        raise HTTPException(status_code=400, detail=f"Could not parse {file_type} file: {e}")

    file_id = f"{id_prefix}_{__import__('uuid').uuid4()}"
    logger.info(f"{file_type} file uploaded: {file_id} ({result['file_type']})")

    return FileUploadResponse(
        status="uploaded",
        file_id=file_id,
        file_type=file_type,
        preview=result["preview"],
    )


@router.post("/calendar/upload")
async def upload_calendar(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> FileUploadResponse:
    """Upload the annual calendar as CSV or PDF (specs.md 3.1)."""
    return await _upload_and_ingest("calendario", "cal", (".csv", ".pdf"), file, db)


@router.post("/teachers/upload")
async def upload_teachers(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> FileUploadResponse:
    """Upload the docenti CSV."""
    return await _upload_and_ingest("docenti", "doc", (".csv",), file, db)


@router.post("/classes/upload")
async def upload_classes(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> FileUploadResponse:
    """Upload the classi CSV."""
    return await _upload_and_ingest("classi", "cls", (".csv",), file, db)


@router.post("/subjects/upload")
async def upload_subjects(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> FileUploadResponse:
    """Upload the materie CSV."""
    return await _upload_and_ingest("materie", "mat", (".csv",), file, db)


@router.post("/assignments/upload")
async def upload_assignments(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> FileUploadResponse:
    """Upload the assegnazioni CSV."""
    return await _upload_and_ingest("assegnazioni", "asg", (".csv",), file, db)


@router.post("/class-pairings/upload")
async def upload_class_pairings(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> FileUploadResponse:
    """Upload the accoppiamenti CSV (optional)."""
    return await _upload_and_ingest("accoppiamenti", "acc", (".csv",), file, db)


@router.post("/setup/validate")
def validate_setup(
    file_data: Dict[str, Any],
    db: Session = Depends(get_db),
) -> SetupValidationResponse:
    """
    Validate all setup files and check coherence.

    Preferred: each file was already uploaded via its own /api/*/upload
    endpoint, and this call just carries `{"file_ids": [...]}` (the ids
    themselves aren't inspected - the already-parsed data lives server-side
    by the time this runs). Also accepts raw CSV text directly per field
    (`{"docenti": "csv content", ...}`) for API-only usage without a prior
    upload.
    """
    try:
        service = _get_setup_service(db)
        result = service.parse_and_validate_files(file_data)
        return result

    except ValueError as e:
        logger.error(f"Validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/setup/validate-field")
def validate_single_field(
    request: FieldValidationRequest,
    db: Session = Depends(get_db),
) -> FieldValidationResponse:
    """
    Real-time validation as admin corrects field values.
    """
    try:
        service = _get_setup_service(db)
        result = service.validate_field_correction(
            file_type=request.file_type,
            entity_identifier=request.entity,
            field=request.field,
            new_value=request.new_value,
        )
        return result

    except Exception as e:
        logger.error(f"Field validation error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/setup/apply-correction")
def apply_correction(
    request: CorrectionRequest,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Commit a field correction confirmed in the setup wizard's
    CorrectionForm ("Salva correzione"). `request.correction` carries
    {field, entity, new_value} - `file_type` isn't sent by the frontend,
    it's resolved from `file_id`'s own prefix (see SetupService.apply_correction).
    """
    correction = request.correction or {}

    try:
        service = _get_setup_service(db)
        return service.apply_correction(
            file_id=request.file_id,
            entity_identifier=correction.get("entity"),
            field=correction.get("field"),
            new_value=correction.get("new_value"),
        )

    except ValueError as e:
        logger.warning(f"Correction error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error applying correction: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/calendar/add-date-manual")
def add_calendar_date_manual(
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    Manually add one calendar date - the fallback for a date the OCR/PDF
    calendar parser missed (specs.md 3.1). Request:
    {file_id, date, ore_max_giornata, flag_chiusura, flag_stage_classe_id}.
    """
    try:
        try:
            parsed_date = date.fromisoformat(str(payload["date"]))
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=400, detail=f"Invalid or missing date: {payload.get('date')!r}")

        service = _get_setup_service(db)
        total = service.add_calendar_date_manual(
            data=parsed_date,
            ore_max_giornata=payload["ore_max_giornata"],
            flag_chiusura=payload.get("flag_chiusura", False),
            flag_stage_classe_id=payload.get("flag_stage_classe_id"),
        )
        return {"status": "added", "total_dates_loaded": total}

    except HTTPException:
        raise
    except (KeyError, ValueError) as e:
        logger.warning(f"Manual calendar date error: {e}")
        raise HTTPException(status_code=400, detail=str(e) or "Missing required field")
    except Exception as e:
        logger.error(f"Unexpected error adding manual calendar date: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/setup/save")
def save_setup_data(
    request: SetupSaveRequest,
    db: Session = Depends(get_db),
) -> SetupSaveResponse:
    """
    Save all validated setup data to database.
    """
    try:
        service = _get_setup_service(db)

        result = service.apply_and_save_setup(
            scuola_id=_get_current_school_id(),
            school_name=request.school_name,
            school_year=request.school_year,
            data_inizio=request.data_inizio,
            data_fine=request.data_fine,
        )

        # Clean up service instance so the next setup flow starts fresh
        global _setup_service
        _setup_service = None

        return result

    except Exception as e:
        logger.error(f"Setup save error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
