"""
Password hashing and session helpers for the admin login (app/routes/auth.py)
and for gating every other router behind get_current_admin (see its use as
an APIRouter-level `dependencies=[Depends(get_current_admin)]` in
setup/availability/schedule/chat/dati - app/routes/*.py).

Uses PBKDF2-HMAC-SHA256 from the standard library instead of an extra
dependency (bcrypt/passlib) - this is a single-admin MVP, not a
multi-tenant system, so stdlib hashing is a reasonable fit.
"""

import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Admin, AdminSession

_PBKDF2_ITERATIONS = 260_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    )
    return f"{salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest_hex = stored.split("$", 1)
    except ValueError:
        return False
    expected = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(expected.hex(), digest_hex)


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def extract_bearer_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip()


def get_current_admin(
    authorization: Optional[str] = Header(None), db: Session = Depends(get_db)
) -> Admin:
    """FastAPI dependency that every protected router requires - raises 401
    unless the request carries a live (non-expired) session token."""
    token = extract_bearer_token(authorization)
    session = db.query(AdminSession).filter(AdminSession.token == token).first() if token else None
    if not session or session.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Not authenticated")
    admin = db.query(Admin).filter(Admin.id == session.admin_id).first()
    if not admin:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return admin


ROLE_ADMIN = "ADMIN"
ROLE_SEGRETERIA = "SEGRETERIA"
ROLES = (ROLE_ADMIN, ROLE_SEGRETERIA)

_READ_METHODS = {"GET", "HEAD", "OPTIONS"}


def _is_admin_role(admin: Admin) -> bool:
    # A missing role (accounts created before roles existed) means full admin.
    return (admin.role or ROLE_ADMIN) == ROLE_ADMIN


def require_admin(admin: Admin = Depends(get_current_admin)) -> Admin:
    """Full-admin only: 403 for any other role (e.g. SEGRETERIA)."""
    if not _is_admin_role(admin):
        raise HTTPException(status_code=403, detail="Permesso negato: serve un account amministratore")
    return admin


def require_admin_for_writes(
    request: Request, admin: Admin = Depends(get_current_admin)
) -> Admin:
    """Any logged-in user may read; only a full admin may change anything."""
    if request.method not in _READ_METHODS and not _is_admin_role(admin):
        raise HTTPException(status_code=403, detail="Permesso negato: account in sola lettura")
    return admin
