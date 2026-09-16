from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from app.database import get_db
from app.models import Admin, AdminSession
from app.security import verify_password, generate_session_token, extract_bearer_token, get_current_admin
from app.schemas import LoginRequest, LoginResponse
import logging

logger = logging.getLogger(__name__)
router = APIRouter()

SESSION_TTL = timedelta(days=7)


@router.post("/auth/login", response_model=LoginResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    """Verify credentials against the Admin table and issue a bearer session token.
    The admin account itself is created via scripts/create_admin.py, not here."""
    email = data.email.strip().lower()
    admin = db.query(Admin).filter(Admin.email == email).first()
    if not admin or not verify_password(data.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Email o password non corretti")

    token = generate_session_token()
    db.add(AdminSession(token=token, admin_id=admin.id, expires_at=datetime.utcnow() + SESSION_TTL))
    db.commit()
    return LoginResponse(status="ok", token=token, email=admin.email)


@router.post("/auth/logout")
def logout(authorization: Optional[str] = Header(None), db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Deletes the session row for this token if there is one - works even on an
    already-expired token, unlike get_current_admin, since logging out should
    always succeed client-side."""
    token = extract_bearer_token(authorization)
    if token:
        db.query(AdminSession).filter(AdminSession.token == token).delete()
        db.commit()
    return {"status": "ok"}


@router.get("/auth/me")
def me(admin: Admin = Depends(get_current_admin)) -> Dict[str, Any]:
    return {"email": admin.email}
