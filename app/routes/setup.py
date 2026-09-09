from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session
from datetime import date
from typing import Dict, Any
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

# Global service instance for setup flow (session-scoped cache)
# In production, use proper session management
_setup_service: Dict[str, SetupService] = {}


def _get_current_school_id() -> str:
    """TODO: Get from auth context."""
    return "sch_1"


def _get_setup_service(db: Session) -> SetupService:
    """Get or create SetupService for this session."""
    session_id = id(db)  # Use DB session id as session identifier
    if session_id not in _setup_service:
        _setup_service[session_id] = SetupService(db)
    return _setup_service[session_id]


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

        # Clean up service instance
        session_id = id(db)
        if session_id in _setup_service:
            del _setup_service[session_id]

        return result

    except Exception as e:
        logger.error(f"Setup save error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
