"""
One-off: scale the monte ore for weeks that were approved BEFORE approving
started to scale hours (ScheduleService.approve_schedule). Those weeks are
APPROVATO with approved_at NULL (approving now always sets it), so each one is
processed exactly once: its hours are added to ore_erogate and approved_at is
set, which also makes re-running this script safe.

Usage:
    python -m scripts.backfill_ore_erogate            # show what would change
    python -m scripts.backfill_ore_erogate --apply    # do it
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import AuditLog, OrarioSettimanale  # noqa: E402
from app.services.schedule import ScheduleService  # noqa: E402


def main(apply: bool) -> None:
    db = SessionLocal()
    try:
        weeks = (
            db.query(OrarioSettimanale)
            .filter(OrarioSettimanale.stato == "APPROVATO", OrarioSettimanale.approved_at.is_(None))
            .order_by(OrarioSettimanale.settimana_inizio)
            .all()
        )
        if not weeks:
            print("Nothing to do: no week approved before the monte-ore scaling.")
            return
        service = ScheduleService(db)
        for orario in weeks:
            res = service.scale_monte_ore(orario.scuola_id, orario)
            print(f"{orario.settimana_inizio}: {res['ore_scalate']}h on {res['assegnazioni_aggiornate']} "
                  f"assegnazioni ({res['senza_monte_ore']} without monte ore row)")
            orario.approved_at = datetime.utcnow()
            db.add(AuditLog(
                scuola_id=orario.scuola_id, orario_settimanale_id=orario.id,
                azione="BACKFILL_ORE_EROGATE", dettagli=res,
            ))
        if apply:
            db.commit()
            print("Applied.")
        else:
            db.rollback()
            print("Dry run: nothing written. Re-run with --apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main("--apply" in sys.argv)
