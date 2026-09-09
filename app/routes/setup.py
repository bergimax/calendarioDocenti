from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Dict, Any, List
from app.database import get_db
from app.repositories.setup import SetupRepository
from app.schemas import (
    FileUploadResponse,
    SetupValidationResponse,
    FieldValidationRequest,
    FieldValidationResponse,
    SetupSaveRequest,
    SetupSaveResponse,
)

router = APIRouter()


def _get_current_school_id() -> str:
    """TODO: Get from auth context."""
    return "sch_1"


@router.post("/calendar/upload")
async def upload_calendar(file: UploadFile = File(...)) -> FileUploadResponse:
    """
    Upload calendar PDF file.
    Returns file_id for later processing.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files allowed")

    # TODO: Save file to temp storage (S3 or filesystem)
    file_id = f"cal_{__import__('uuid').uuid4()}"

    return FileUploadResponse(
        status="uploaded",
        file_id=file_id,
        file_type="calendario",
        preview=None,
    )


@router.post("/setup/validate")
def validate_setup(
    file_ids: List[str],
    db: Session = Depends(get_db),
) -> SetupValidationResponse:
    """
    Validate all uploaded files.
    Attempts OCR + parsing.
    Returns structured feedback per file type.
    """
    # TODO: Implement full validation logic
    # For now, return placeholder response

    return SetupValidationResponse(
        status="validation_complete",
        results={
            "calendario": {
                "success": True,
                "preview": {"dates_extracted": 180},
                "warnings": [],
                "errors": [],
            }
        },
        overall_status="ready",
        can_proceed=True,
    )


@router.post("/setup/validate-field")
def validate_single_field(request: FieldValidationRequest) -> FieldValidationResponse:
    """
    Real-time validation as admin types field values.
    """
    # TODO: Implement field validation logic

    return FieldValidationResponse(
        valid=True,
        message="Validato ✓",
        suggestions=[],
    )


@router.post("/setup/save")
def save_setup_data(
    request: SetupSaveRequest,
    db: Session = Depends(get_db),
) -> SetupSaveResponse:
    """
    Save all validated setup data to database in transaction.
    """
    try:
        repo = SetupRepository(db)

        # 1. Create school
        scuola = repo.create_school(
            nome=request.school_name,
            anno_formativo=request.school_year,
            data_inizio_anno=request.data_inizio or datetime.now().date(),
            data_fine_anno=request.data_fine or datetime.now().date(),
        )

        # TODO: Get parsed data from cache (based on file_ids)
        # For now, assume empty lists
        classi_data = []
        docenti_data = []
        materie_data = []
        calendario_data = []
        assegnazioni_data = []
        accoppiamenti_data = []

        # 2. Bulk create classes
        classe_map = repo.bulk_create_classes(scuola.id, classi_data)

        # 3. Bulk create teachers
        docenti_map = repo.bulk_create_teachers(scuola.id, docenti_data)

        # 4. Bulk create subjects
        materie_map = repo.bulk_create_subjects(scuola.id, materie_data)

        # 5. Bulk create calendar
        repo.bulk_create_calendar(scuola.id, calendario_data)

        # 6. Bulk create assignments
        repo.bulk_create_assignments(
            scuola.id, assegnazioni_data, docenti_map, classe_map, materie_map
        )

        # 7. Bulk create paired classes
        repo.bulk_create_paired_classes(scuola.id, accoppiamenti_data, classe_map, materie_map)

        # 8. Commit transaction
        repo.commit()

        # TODO: Clear temp files

        return SetupSaveResponse(
            status="setup_complete",
            school_id=scuola.id,
            next_page=f"/disponibilita/1",
        )

    except Exception as e:
        repo.rollback()
        raise HTTPException(status_code=500, detail=str(e))
