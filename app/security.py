"""
Password hashing and session token helpers for the admin login (app/routes/auth.py).

Uses PBKDF2-HMAC-SHA256 from the standard library instead of an extra
dependency (bcrypt/passlib) - this is a single-admin MVP, not a
multi-tenant system, so stdlib hashing is a reasonable fit.
"""

import hashlib
import hmac
import secrets

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
