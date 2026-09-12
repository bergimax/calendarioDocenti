from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session
from datetime import date
from typing import Dict, Any, Optional
from app.database import get_db
from app.services.setup import SetupService
from app.schemas import (
    FileUploadResponse,
    SetupValidationResponse,
    FieldValidationRequest,
    FieldValidationResponse,
    SetupSaveRequest,
    SetupSaveResponse,
)
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

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


@router.post("/calendar/upload")
async def upload_calendar(file: UploadFile = File(...)) -> FileUploadResponse:
    """
    Upload calendar CSV file.
    Returns file_id for later processing.
    """
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV files allowed for calendar")

    # Read file content
    content = await file.read()
    csv_content = content.decode("utf-8")

    file_id = f"cal_{__import__('uuid').uuid4()}"

    logger.info(f"Calendar file uploaded: {file_id}")

    return FileUploadResponse(
        status="uploaded",
        file_id=file_id,
        file_type="calendario",
        preview={"bytes": len(csv_content)},
    )


@router.post("/setup/validate")
def validate_setup(
    file_data: Dict[str, str],
    db: Session = Depends(get_db),
) -> SetupValidationResponse:
    """
    Validate all setup files.
    Parses CSV content and checks coherence.

    Request body: {
        "calendario": "csv content",
        "docenti": "csv content",
        ...
    }
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
