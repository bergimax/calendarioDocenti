"""
Business logic for school setup (onboarding) flow.
Handles file upload, parsing, validation, corrections, and final save.
"""

from sqlalchemy.orm import Session
from datetime import date, datetime
from typing import Dict, Any, List, Optional, Tuple
from app.repositories.setup import SetupRepository
from app.domain.parser import CalendarParser
from app.domain.validator import DataValidator
from app.schemas import (
    SetupValidationResponse, FileValidationResult, ValidationWarning, ValidationError,
    FieldValidationResponse, SetupSaveResponse
)
import logging

logger = logging.getLogger(__name__)


class SetupService:
    """Business logic for setup/onboarding flow."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = SetupRepository(db)

        # Cache parsed data during setup flow (session-scoped)
        self.parsed_data_cache: Dict[str, Any] = {}

    def parse_and_validate_files(
        self,
        file_data: Dict[str, Optional[str]],
    ) -> SetupValidationResponse:
        """
        Parse all uploaded files and validate coherence.

        file_data format: {
            "calendario": "csv content",
            "docenti": "csv content",
            "classi": "csv content",
            "materie": "csv content",
            "assegnazioni": "csv content",
            "accoppiamenti": "csv content" (optional)
        }

        Returns: SetupValidationResponse with results per file type
        """
        logger.info("Starting parse and validate flow")

        results = {}
        parsed_data = {}

        # 1. Parse each file type
        file_parsers = {
            "calendario": (CalendarParser.parse_calendar_csv, "Calendar"),
            "docenti": (CalendarParser.parse_docenti_csv, "Teachers"),
            "classi": (CalendarParser.parse_classi_csv, "Classes"),
            "materie": (CalendarParser.parse_materie_csv, "Subjects"),
            "assegnazioni": (CalendarParser.parse_assegnazioni_csv, "Assignments"),
            "accoppiamenti": (CalendarParser.parse_accoppiamenti_csv, "Paired Classes"),
        }

        for file_type, (parser_func, display_name) in file_parsers.items():
            csv_content = file_data.get(file_type)

            if not csv_content:
                # Optional file (accoppiamenti)
                if file_type == "accoppiamenti":
                    results[file_type] = FileValidationResult(
                        success=True,
                        preview={"count": 0},
                        warnings=[],
                        errors=[],
                    )
                    parsed_data[file_type] = []
                else:
                    results[file_type] = FileValidationResult(
                        success=False,
                        preview=None,
                        warnings=[],
                        errors=[ValidationError(
                            type="missing_file",
                            message=f"{display_name} data not provided"
                        )],
                    )
                continue

            try:
                parsed = parser_func(csv_content)
                parsed_data[file_type] = parsed

                # Build preview
                if file_type == "calendario":
                    preview = {
                        "count": len(parsed),
                        "date_range": f"{min(p['data'] for p in parsed)} to {max(p['data'] for p in parsed)}" if parsed else "N/A",
                        "closures": sum(1 for p in parsed if p.get("flag_chiusura"))
                    }
                elif file_type == "docenti":
                    preview = {
                        "count": len(parsed),
                        "assunti": sum(1 for p in parsed if p["tipo"] == "ASSUNTO"),
                        "contratti": sum(1 for p in parsed if p["tipo"] == "CONTRATTO"),
                    }
                else:
                    preview = {"count": len(parsed)}

                results[file_type] = FileValidationResult(
                    success=True,
                    preview=preview,
                    warnings=[],
                    errors=[],
                )

            except Exception as e:
                logger.error(f"Error parsing {file_type}: {e}")
                results[file_type] = FileValidationResult(
                    success=False,
                    preview=None,
                    warnings=[],
                    errors=[ValidationError(
                        type="parse_error",
                        message=str(e)
                    )],
                )

        # 2. Cross-validate coherence
        if all(r.success for r in results.values()):
            valid, errors = DataValidator.validate_all_data(
                docenti=parsed_data.get("docenti", []),
                classi=parsed_data.get("classi", []),
                materie=parsed_data.get("materie", []),
                assegnazioni=parsed_data.get("assegnazioni", []),
                accoppiamenti=parsed_data.get("accoppiamenti", []),
                calendario=parsed_data.get("calendario", []),
            )

            if not valid:
                # Add cross-validation errors to relevant file results
                for error_msg in errors:
                    # Try to infer which file this error belongs to
                    if "assignment" in error_msg.lower():
                        results["assegnazioni"].errors.append(
                            ValidationError(type="coherence", message=error_msg)
                        )
                    elif "pairing" in error_msg.lower():
                        results["accoppiamenti"].errors.append(
                            ValidationError(type="coherence", message=error_msg)
                        )
                    elif "calendar" in error_msg.lower():
                        results["calendario"].errors.append(
                            ValidationError(type="coherence", message=error_msg)
                        )
                    else:
                        # Add to first file with errors
                        for file_key in results:
                            if not results[file_key].errors:
                                results[file_key].errors.append(
                                    ValidationError(type="coherence", message=error_msg)
                                )
                                break

        # 3. Cache parsed data for later use
        self.parsed_data_cache = parsed_data

        # Determine overall status
        overall_status = "ready" if all(r.success and not r.errors for r in results.values()) else "errors"
        can_proceed = all(r.success for r in results.values())

        logger.info(f"Validation complete: status={overall_status}, can_proceed={can_proceed}")

        return SetupValidationResponse(
            status="validation_complete",
            results=results,
            overall_status=overall_status,
            can_proceed=can_proceed,
        )

    def validate_field_correction(
        self,
        file_type: str,
        entity_identifier: str,
        field: str,
        new_value: str,
    ) -> FieldValidationResponse:
        """
        Real-time validation of a corrected field.
        """
        logger.info(f"Validating field correction: {file_type}/{entity_identifier}/{field}")

        try:
            # Get cached data
            parsed_data = self.parsed_data_cache.get(file_type)
            if not parsed_data:
                return FieldValidationResponse(
                    valid=False,
                    message=f"No cached data for {file_type}",
                )

            # Find entity
            entity = None
            if file_type == "docenti":
                entity = next((d for d in parsed_data if d["nome"] == entity_identifier), None)
                if not entity:
                    return FieldValidationResponse(
                        valid=False,
                        message=f"Teacher '{entity_identifier}' not found",
                    )
                # Validate field
                entity[field] = new_value
                valid, error = DataValidator.validate_docente(entity)
                if not valid:
                    return FieldValidationResponse(valid=False, message=error)

            elif file_type == "classi":
                entity = next((c for c in parsed_data if c["nome"] == entity_identifier), None)
                if not entity:
                    return FieldValidationResponse(
                        valid=False,
                        message=f"Class '{entity_identifier}' not found",
                    )
                entity[field] = new_value
                valid, error = DataValidator.validate_classe(entity)
                if not valid:
                    return FieldValidationResponse(valid=False, message=error)

            elif file_type == "materie":
                entity = next((m for m in parsed_data if m["nome"] == entity_identifier), None)
                if not entity:
                    return FieldValidationResponse(
                        valid=False,
                        message=f"Subject '{entity_identifier}' not found",
                    )
                entity[field] = new_value
                valid, error = DataValidator.validate_materia(entity)
                if not valid:
                    return FieldValidationResponse(valid=False, message=error)

            else:
                return FieldValidationResponse(
                    valid=False,
                    message=f"Unsupported file type for field validation: {file_type}",
                )

            # If we got here, validation passed
            logger.info(f"Field validation passed for {file_type}/{entity_identifier}/{field}")
            return FieldValidationResponse(
                valid=True,
                message="✓ Valid",
                suggestions=[],
            )

        except Exception as e:
            logger.error(f"Error validating field: {e}")
            return FieldValidationResponse(
                valid=False,
                message=f"Validation error: {str(e)}",
            )

    def apply_and_save_setup(
        self,
        scuola_id: str,
        school_name: str,
        school_year: str,
        data_inizio: Optional[date] = None,
        data_fine: Optional[date] = None,
    ) -> SetupSaveResponse:
        """
        Apply final corrections and save all data to database.
        """
        logger.info(f"Saving setup for school '{school_name}' ({school_year})")

        try:
            if not self.parsed_data_cache:
                return SetupSaveResponse(
                    status="error",
                    message="No parsed data in cache. Parse files first.",
                )

            # Get parsed data
            calendario = self.parsed_data_cache.get("calendario", [])
            docenti = self.parsed_data_cache.get("docenti", [])
            classi = self.parsed_data_cache.get("classi", [])
            materie = self.parsed_data_cache.get("materie", [])
            assegnazioni = self.parsed_data_cache.get("assegnazioni", [])
            accoppiamenti = self.parsed_data_cache.get("accoppiamenti", [])

            # Determine date range
            if not data_inizio and calendario:
                data_inizio = min(c["data"] for c in calendario)
            if not data_fine and calendario:
                data_fine = max(c["data"] for c in calendario)

            data_inizio = data_inizio or date.today()
            data_fine = data_fine or date.today()

            # Create school (fixed scuola_id so every other endpoint, which is
            # hardcoded to it in v1 single-tenant mode, can find this data)
            scuola = self.repo.create_school(
                nome=school_name,
                anno_formativo=school_year,
                data_inizio_anno=data_inizio,
                data_fine_anno=data_fine,
                scuola_id=scuola_id,
            )

            logger.info(f"Created school: {scuola.id}")

            # Bulk create entities
            classe_map = self.repo.bulk_create_classes(scuola.id, classi)
            docenti_map = self.repo.bulk_create_teachers(scuola.id, docenti)
            materie_map = self.repo.bulk_create_subjects(scuola.id, materie)

            self.repo.bulk_create_calendar(scuola.id, calendario)
            self.repo.bulk_create_assignments(scuola.id, assegnazioni, docenti_map, classe_map, materie_map)
            self.repo.bulk_create_paired_classes(scuola.id, accoppiamenti, classe_map, materie_map)

            # Commit transaction
            self.repo.commit()

            logger.info(f"Setup saved successfully: {scuola.id}")

            # Clear cache
            self.parsed_data_cache = {}

            return SetupSaveResponse(
                status="setup_complete",
                school_id=scuola.id,
                next_page="/disponibilita/1",
            )

        except Exception as e:
            self.repo.rollback()
            logger.error(f"Error saving setup: {e}", exc_info=True)
            return SetupSaveResponse(
                status="error",
                message=f"Database error: {str(e)}",
            )
