"""
Incident trigger for the on-call demo (see docs/oncall-agent.md).

With oncall/demo/regression.patch applied, a teacher availability record that has an
unavailable slot without `ora_inizio` makes timetable generation crash. This script
plants such a record in the running local stack's database and then asks for a
timetable, i.e. exactly what an admin would experience.

Usage: python oncall/demo/trigger_incident.py   (stack started with `make up`)
"""

import subprocess
import sys
from datetime import date, timedelta

import httpx

BASE = "http://localhost:8080"
COMPOSE = ["docker", "compose", "-f", "docker-compose.local.yml"]

PLANT = """
from app.database import SessionLocal
from app.models import Docente, DisponibilitaSettimanale
from datetime import date
week = date.fromisoformat("{week}")
with SessionLocal() as db:
    d = db.query(Docente).first()
    row = db.query(DisponibilitaSettimanale).filter_by(docente_id=d.id, settimana_inizio=week).first()
    if row is None:
        row = DisponibilitaSettimanale(scuola_id=d.scuola_id, docente_id=d.id, settimana_inizio=week, giorni_fasce={{}})
        db.add(row)
    row.giorni_fasce = {{"lunedi": [{{"disponibile": False}}]}}  # malformed slot: no ora_inizio
    db.commit()
print("planted malformed availability for one teacher")
"""


def main() -> None:
    week = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
    subprocess.run(COMPOSE + ["exec", "-T", "backend", "python", "-c", PLANT.format(week=week)], check=True)
    token = httpx.post(f"{BASE}/api/auth/login", json={"email": "admin@example.com", "password": "admin1234"}).json()["token"]
    r = httpx.post(f"{BASE}/api/schedule/generate", json={"week_start": str(week)},
                   headers={"Authorization": f"Bearer {token}"}, timeout=120).json()
    print("generate ->", r["status"], "|", (r.get("message") or "")[:120])
    if r["status"] != "error":
        sys.exit("expected the regression to make generation fail; is oncall/demo/regression.patch applied and `make up` re-run?")


if __name__ == "__main__":
    main()
