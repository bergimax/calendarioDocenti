from pydantic import BaseModel, Field, EmailStr
from typing import List, Dict, Optional, Any
from datetime import date, datetime
from enum import Enum


# Enums
class DocenteTipo(str, Enum):
    ASSUNTO = "ASSUNTO"
    CONTRATTO = "CONTRATTO"


class MateriaTipo(str, Enum):
    TEORIA = "TEORIA"
    PRATICA = "PRATICA"


class PesoCognitivo(str, Enum):
    ALTO = "ALTO"
    MEDIO = "MEDIO"
    BASSO = "BASSO"


class Giorno(str, Enum):
    LUNEDI = "LUNEDI"
    MARTEDI = "MARTEDI"
    MERCOLEDI = "MERCOLEDI"
    GIOVEDI = "GIOVEDI"
    VENERDI = "VENERDI"


class OrarioStato(str, Enum):
    BOZZA = "BOZZA"
    APPROVATO = "APPROVATO"


class QualityLevel(str, Enum):
    A = "A"
    B = "B"
    C = "C"


# ===== Availability Schemas =====

class HourSlot(BaseModel):
    """Single hour slot availability."""
    ora_inizio: str  # "08:00"
    ora_fine: str    # "09:00"
    disponibile: bool


class GiorniFasceDict(BaseModel):
    """Dictionary of day -> list of hour slots."""
    lunedi: List[HourSlot]
    martedi: List[HourSlot]
    mercoledi: List[HourSlot]
    giovedi: List[HourSlot]
    venerdi: List[HourSlot]


class AvailabilityResponse(BaseModel):
    """Response for get/save availability."""
    teacher_id: str
    week_start: date
    giorni_fasce: Dict[str, List[Dict[str, Any]]]
    is_default: Optional[bool] = False
    is_inherited: Optional[bool] = False

    class Config:
        from_attributes = True


class AvailabilitySaveRequest(BaseModel):
    """Request to save availability."""
    giorni_fasce: Dict[str, List[Dict[str, Any]]]


# ===== Setup Schemas =====

class FileUploadResponse(BaseModel):
    """Response from file upload."""
    status: str
    file_id: str
    file_type: str
    preview: Optional[Dict[str, Any]] = None


class ValidationWarning(BaseModel):
    """Validation warning: a non-fatal data-quality issue tied to one named
    entity (a docente/classe/materia nome), so the setup wizard can offer a
    direct "Correggi" shortcut for it."""
    entity: str
    issue: str


class ValidationError(BaseModel):
    """Validation error."""
    type: str
    message: str


class FileValidationResult(BaseModel):
    """Validation result per file type."""
    success: bool
    preview: Optional[Dict[str, Any]] = None
    warnings: List[ValidationWarning] = []
    errors: List[ValidationError] = []


class SetupValidationResponse(BaseModel):
    """Response from setup validation."""
    status: str
    results: Dict[str, FileValidationResult]
    overall_status: str
    can_proceed: bool


class FieldValidationRequest(BaseModel):
    """Request for field validation."""
    file_type: str
    entity: str
    field: str
    new_value: str


class FieldValidationResponse(BaseModel):
    """Response for field validation."""
    valid: bool
    message: str
    suggestions: List[str] = []


class CorrectionRequest(BaseModel):
    """Request to apply correction."""
    file_id: str
    correction: Dict[str, Any]


class SetupSaveRequest(BaseModel):
    """Request to save setup data."""
    file_ids: List[str]
    corrections_applied: List[Dict[str, Any]] = []
    school_name: str
    school_year: str
    data_inizio: Optional[date] = None
    data_fine: Optional[date] = None


class SetupSaveResponse(BaseModel):
    """Response from setup save."""
    status: str
    school_id: Optional[str] = None
    next_page: Optional[str] = None
    message: Optional[str] = None


# ===== Schedule Schemas =====

class SlotLezioneCreate(BaseModel):
    """Slot creation data."""
    classe_id: str
    docente_id: str
    materia_id: str
    giorno: Giorno
    ora_inizio: int
    ora_fine: int
    accoppiata: bool = False
    classe_accoppiata_id: Optional[str] = None


class SlotLezioneResponse(BaseModel):
    """Slot response."""
    slot_id: str
    classe_id: str
    classe_nome: Optional[str] = None
    docente_id: str
    docente_nome: Optional[str] = None
    materia_id: str
    materia_nome: Optional[str] = None
    materia_tipo: Optional[str] = None
    giorno: Giorno
    ora_inizio: int
    ora_fine: int
    accoppiata: bool
    classe_accoppiata_id: Optional[str] = None
    conflitto: bool = False
    # `chiave` of every conflict this lesson is part of (see ScheduleSolver.get_conflicts)
    conflitto_chiavi: List[str] = []
    indisponibile: bool = False

    class Config:
        from_attributes = True


class ScheduleGenerateRequest(BaseModel):
    """Request to generate a weekly schedule."""
    week_start: date
    include_preferences: bool = True


class ScheduleGenerateResponse(BaseModel):
    """Response from schedule generation."""
    status: str  # "generated", "infeasible", "timeout", "error"
    schedule_id: Optional[str] = None
    quality_score: Optional[float] = None
    quality_level: Optional[QualityLevel] = None
    n_soft_conflicts: Optional[int] = None
    slots: Optional[List[SlotLezioneResponse]] = None
    message: Optional[str] = None
    conflicting_constraints: Optional[List[str]] = None
    suggested_deroghe: Optional[List[str]] = None
    # Itemized soft-constraint violations in the generated solution (see
    # ScheduleSolver.get_conflicts) - matches frontend/src/lib/types.ts's Conflict[].
    conflicts: Optional[List[Dict[str, Any]]] = None
    # {classe_id, classe_nome, giorno} for classi on stage this week, so the
    # grid can label them "STAGE" right after generate/regenerate too (the
    # GET response already carries this; see ScheduleRepository._stage_cells_for_week).
    stage_cells: Optional[List[Dict[str, Any]]] = None


class ModifySlotRequest(BaseModel):
    """Request to modify slot."""
    slot_id: str
    changes: Dict[str, Any]  # docente_id, giorno, ora_inizio, etc


class AssignSlotRequest(BaseModel):
    """Manually put a lesson into a free hour (a "forzatura": relaxable rules may end up as conflicts)."""
    classe_id: str
    giorno: Giorno
    ora_inizio: int
    docente_id: str
    materia_id: str


class ApproveConflictRequest(BaseModel):
    """Approve conflicts (by their stable `chiave`): they stop being reported."""
    chiavi: List[str]


class RejectConflictRequest(BaseModel):
    """Reject the lesson (or uncovered hour) at classe/giorno/ora: that hour is left free."""
    classe_id: str
    giorno: Giorno
    ora_inizio: int


class QuickActionRequest(BaseModel):
    """Request to apply quick action."""
    action_type: str  # "force_3_hours_theory", "reduce_contract", etc
    class_id: Optional[str] = None
    teacher_id: Optional[str] = None
    giorno: Optional[str] = None  # "LUNEDI".."VENERDI", GiornoEnum member name
    max_hours: Optional[int] = None
    parameters: Optional[Dict[str, Any]] = None


# ===== Chat Schemas =====

class ChatMessageCreate(BaseModel):
    """Chat message creation."""
    schedule_id: str
    week_start: date
    message: str


class ChatMessageResponse(BaseModel):
    """Chat message response."""
    id: str
    ruolo: str  # "ADMIN" or "AI"
    messaggio: str
    timestamp: datetime

    class Config:
        from_attributes = True


class ChatHistoryResponse(BaseModel):
    """Chat history response."""
    messages: List[ChatMessageResponse]


# ===== Approval & Export Schemas =====

class ApproveScheduleResponse(BaseModel):
    """Response from approve."""
    status: str
    schedule_id: str
    stato: OrarioStato
    approved_at: Optional[datetime] = None


class ExportPDFResponse(BaseModel):
    """Response from PDF export."""
    status: str
    pdf_url: str
    filename: str


# ===== Data Management Schemas =====

class DocentiListResponse(BaseModel):
    """Response for list docenti."""
    id: str
    nome: str
    email: Optional[str]
    tipo: DocenteTipo
    active: bool

    class Config:
        from_attributes = True


class DocentiCreateRequest(BaseModel):
    """Request to create docente."""
    nome: str
    email: Optional[str] = None
    tipo: DocenteTipo


class CalendarioCreateRequest(BaseModel):
    """Request to add calendar date."""
    data: date
    ore_max_giornata: int = 5
    flag_chiusura: bool = False
    flag_stage_classe_id: Optional[str] = None


class CalendarioResponse(BaseModel):
    """Calendar date response."""
    id: str
    data: date
    ore_max_giornata: int
    flag_chiusura: bool
    flag_stage_classe_id: Optional[str]

    class Config:
        from_attributes = True


class LoginRequest(BaseModel):
    """Admin login request."""
    email: str
    password: str


class LoginResponse(BaseModel):
    """Admin login response - token is sent back as a Bearer token."""
    status: str
    token: str
    email: str


class ScheduleFeedbackRequest(BaseModel):
    """Admin rating of a generated schedule (1 = unusable, 5 = perfect)."""
    voto: int = Field(..., ge=1, le=5)
    motivi: List[str] = Field(default_factory=list)
    nota: Optional[str] = Field(None, max_length=2000)


class ApplyWeightsRequest(BaseModel):
    """Accept the pending weight proposals for these soft-constraint kinds (all if omitted)."""
    kinds: Optional[List[str]] = None


class ResetWeightsRequest(BaseModel):
    """Put one soft constraint (or all, if omitted) back to its default weight."""
    kind: Optional[str] = None
