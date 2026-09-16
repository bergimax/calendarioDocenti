"""
One-off script to create (or reset the password of) the school admin
account used by POST /api/auth/login - see app/routes/auth.py. There is no
registration endpoint (v1 is single-admin/single-tenant, see specs.md scope),
so this is the only way to provision the account.

Usage:
    python -m scripts.create_admin <email> <password> [scuola_id]
    (scuola_id defaults to "sch_1", the only school in this v1 app)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.models import Admin  # noqa: E402
from app.security import hash_password  # noqa: E402


def main(email: str, password: str, scuola_id: str = "sch_1") -> None:
    Base.metadata.create_all(bind=engine)
    email = email.strip().lower()

    db = SessionLocal()
    try:
        admin = db.query(Admin).filter(Admin.email == email).first()
        if admin:
            admin.password_hash = hash_password(password)
            print(f"Updated password for existing admin {email!r}.")
        else:
            admin = Admin(scuola_id=scuola_id, email=email, password_hash=hash_password(password))
            db.add(admin)
            print(f"Created admin {email!r} for scuola_id={scuola_id!r}.")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m scripts.create_admin <email> <password> [scuola_id]")
        sys.exit(1)
    main(*sys.argv[1:4])
