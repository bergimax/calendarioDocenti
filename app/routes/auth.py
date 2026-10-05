from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from app.database import get_db
from app.models import Admin, AdminSession
from app.security import verify_password, hash_password, generate_session_token, extract_bearer_token, get_current_admin
from app.schemas import ChangePasswordRequest, LoginRequest, LoginResponse
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
    return LoginResponse(status="ok", token=token, email=admin.email, role=admin.role or "ADMIN")


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
    return {"email": admin.email, "role": admin.role or "ADMIN"}


MIN_PASSWORD_LENGTH = 8


@router.post("/auth/change-password")
def change_password(
    data: ChangePasswordRequest,
    authorization: Optional[str] = Header(None),
    admin: Admin = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Change the logged-in user's password. Needs the current password; every
    other session of this user is closed (this one stays logged in)."""
    if not verify_password(data.current_password, admin.password_hash):
        raise HTTPException(status_code=400, detail="La password attuale non è corretta")
    if len(data.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"La nuova password deve avere almeno {MIN_PASSWORD_LENGTH} caratteri",
        )
    if data.new_password == data.current_password:
        raise HTTPException(status_code=400, detail="La nuova password deve essere diversa da quella attuale")

    admin.password_hash = hash_password(data.new_password)
    token = extract_bearer_token(authorization)
    db.query(AdminSession).filter(
        AdminSession.admin_id == admin.id, AdminSession.token != token
    ).delete()
    db.commit()
    return {"status": "ok"}
