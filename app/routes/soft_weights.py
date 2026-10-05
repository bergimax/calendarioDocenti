from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Admin
from app.schemas import ApplyWeightsRequest, ResetWeightsRequest
from app.security import get_current_admin, require_admin
from app.services.soft_weights import SoftWeightService, UnknownKind

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/soft-weights")
def get_soft_weights(db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Active weights of the tunable soft constraints, pending proposals learned from ratings, and history."""
    return SoftWeightService(db).state()


@router.post("/soft-weights/apply")
def apply_soft_weights(
    request: ApplyWeightsRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Accept the pending proposals (all, or only the listed kinds). Affects the next schedules generated."""
    try:
        return SoftWeightService(db).apply(request.kinds, admin.id)
    except UnknownKind as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/soft-weights/reset")
def reset_soft_weights(
    request: ResetWeightsRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(get_current_admin),
) -> Dict[str, Any]:
    """Restore the default weight of one soft constraint, or of all."""
    try:
        return SoftWeightService(db).reset(request.kind, admin.id)
    except UnknownKind as e:
        raise HTTPException(status_code=422, detail=str(e))
