"""
One-off simulation script: the real imported data (see scripts/import_documenti.py)
left every MonteOreAnnuale.ore_totali at 0 (a documented placeholder - there is no
source PDF with per-class annual hours) and defaulted every Docente.tipo to ASSUNTO
(no source PDF distinguishes assunti from contratto either). Neither is fittable to
the solver as-is: ore_totali=0 means no assignment ever gets scheduled (see
ScheduleSolver's ore_residue <= 0 skip, app/domain/solver.py).

This script fills in both, from values given by the school on 2026-09-16:
- Docente.tipo: ASSUNTO only for the three named teachers, CONTRATTO for everyone
  else.
- MonteOreAnnuale.ore_totali: one of {40, 60, 80, 100, 200} per assignment row,
  picked with a fixed-seed pseudo-random choice (reproducible across re-runs,
  varied across rows - there's exactly one placeholder Materia shared by every
  assignment, so there's no curriculum signal to pick from instead). These are
  plausible per-assignment annual lesson-hour totals (33-38 school weeks x 1-6h/
  week lands in this range), not a per-teacher total to hit - assignment counts
  per teacher vary too much (1 to 17) for a fixed per-teacher target to be
  achievable within these bucket sizes.

Usage:
    python -m scripts.simulate_monte_ore [scuola_id]
    (scuola_id defaults to "sch_1", the only school in this v1 app)
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.models import Docente, MonteOreAnnuale  # noqa: E402

ASSUNTI = {"CRESCINI EDOARDO", "BERTUSSI MARA", "BIASIOLO ALESSIA"}
ORE_BUCKETS = [40, 60, 80, 100, 200]
SEED = 20260916  # fixed, so re-running reproduces the same simulated values


def main(scuola_id: str = "sch_1") -> None:
    db = SessionLocal()
    try:
        docenti = db.query(Docente).filter(Docente.scuola_id == scuola_id).all()
        for d in docenti:
            d.tipo = "ASSUNTO" if d.nome.strip().upper() in ASSUNTI else "CONTRATTO"
        db.commit()
        print(f"Set tipo on {len(docenti)} docenti "
              f"({sum(1 for d in docenti if d.tipo == 'ASSUNTO')} ASSUNTO, "
              f"{sum(1 for d in docenti if d.tipo == 'CONTRATTO')} CONTRATTO).")

        rows = (
            db.query(MonteOreAnnuale)
            .filter(MonteOreAnnuale.scuola_id == scuola_id)
            .order_by(MonteOreAnnuale.id)
            .all()
        )
        rng = random.Random(SEED)
        for row in rows:
            row.ore_totali = rng.choice(ORE_BUCKETS)
            row.ore_erogate = 0
        db.commit()
        print(f"Set ore_totali on {len(rows)} monte_ore_annuale rows "
              f"(total simulated annual hours: {sum(r.ore_totali for r in rows)}).")
    finally:
        db.close()


if __name__ == "__main__":
    main(*sys.argv[1:2])
