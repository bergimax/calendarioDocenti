"""
One-off script: every DisponibilitaSettimanale row currently on file (for
every docente, every existing week) is the AvailabilityService default grid
- fully available 8-14, every day - because no CONTRATTO docente has ever
saved a real availability through the UI yet. That's wrong for CONTRATTO
docenti specifically: app/domain/solver.py's _constraint_teacher_availability
only enforces giorni_fasce for CONTRATTO (ASSUNTO is implicitly available
8-14 every day, see that method), so a placeholder "always available"
CONTRATTO grid gives the solver no real signal to work with.

Real per-day availability isn't known yet (no source document has it - the
school confirmed 2026-09-16 there's no such record), so this derives a
plausible one from each CONTRATTO docente's real weekly teaching load
instead: the number of distinct (giorno, ora) hours they're seen teaching
ANY class in Documenti/es_di_calendario.pdf (same source
scripts/rederive_monte_ore_and_pairings.py uses for MonteOreAnnuale -
deduplicated across classes here, not summed, since a docente teaching two
classes at the same hour - a paired lesson - is still only one hour of their
own time). Days available = hours / 6, rounded (a part-time docente is
assumed to teach a full 6h day on each day they come in, not spread thin
across every day) - e.g. 12h/week -> 2 days, 18h/week -> 3 days, 6h/week ->
1 day, clamped to [1, 5]. WHICH days is arbitrary with no real signal to
pick from, so it's a fixed-seed random choice per docente (reproducible
across re-runs). Applies the same day pattern to every existing week's row
for that docente (a part-time contract's weekly availability is normally
stable, not different week to week).

ASSUNTO docenti are left untouched - their availability is never enforced
by the solver either way (see above).

Usage:
    python -m scripts.set_contratto_availability [scuola_id]
"""

import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, Set

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.domain.parser import GIORNI_ORDINE, SchoolRosterParser  # noqa: E402
from app.models import Docente, DisponibilitaSettimanale  # noqa: E402

PDF_PATH = Path(__file__).resolve().parent.parent / "Documenti" / "es_di_calendario.pdf"
SEED = 20260918  # fixed, so re-running reproduces the same simulated days
ORE_GIORNO = list(range(8, 14))  # 08:00-14:00, matching the availability grid


def _resolve_cognome(cognome: str, known_cognomi: Set[str]):
    import difflib
    if cognome in known_cognomi:
        return cognome
    close = difflib.get_close_matches(cognome, known_cognomi, n=1, cutoff=0.8)
    return close[0] if close else None


def main(scuola_id: str = "sch_1") -> None:
    data = SchoolRosterParser.parse_orario_settimanale_pdf(PDF_PATH.read_bytes())
    slots = data["slots"]

    db = SessionLocal()
    try:
        docenti = db.query(Docente).filter_by(scuola_id=scuola_id).all()
        docente_id_by_cognome: Dict[str, str] = {}
        known_cognomi: Set[str] = set()
        for d in docenti:
            cognome = d.nome.strip().split()[0].upper()
            docente_id_by_cognome[cognome] = d.id
            known_cognomi.add(cognome)
        contratto_ids = {d.id for d in docenti if d.tipo == "CONTRATTO"}

        weekly_cells: Dict[str, Set] = defaultdict(set)  # docente_id -> {(giorno, ora), ...}
        for s in slots:
            cognome = _resolve_cognome(s["docente_cognome"], known_cognomi)
            if not cognome:
                continue
            docente_id = docente_id_by_cognome.get(cognome)
            if not docente_id or docente_id not in contratto_ids:
                continue
            weekly_cells[docente_id].add((s["giorno"], s["ora_inizio"]))

        rng = random.Random(SEED)
        n_docenti_updated, n_rows_updated = 0, 0
        for docente_id in sorted(contratto_ids):
            weekly_hours = len(weekly_cells.get(docente_id, ()))
            if weekly_hours == 0:
                continue
            n_giorni = max(1, min(5, round(weekly_hours / 6)))
            giorni_disponibili = set(rng.sample(GIORNI_ORDINE, n_giorni))

            giorni_fasce = {
                giorno: [
                    {
                        "ora_inizio": f"{h:02d}:00",
                        "ora_fine": f"{h + 1:02d}:00",
                        "disponibile": giorno in giorni_disponibili,
                    }
                    for h in ORE_GIORNO
                ]
                for giorno in GIORNI_ORDINE
            }

            rows = db.query(DisponibilitaSettimanale).filter_by(
                scuola_id=scuola_id, docente_id=docente_id,
            ).all()
            for row in rows:
                row.giorni_fasce = giorni_fasce
                n_rows_updated += 1
            n_docenti_updated += 1

            docente_nome = next(d.nome for d in docenti if d.id == docente_id)
            print(f"  {docente_nome}: {weekly_hours}h/settimana -> {n_giorni} giorni "
                  f"({', '.join(sorted(giorni_disponibili, key=GIORNI_ORDINE.index))})")

        db.commit()
        print(f"DisponibilitaSettimanale: {n_docenti_updated} docenti CONTRATTO aggiornati "
              f"({n_rows_updated} righe/settimane toccate).")
    finally:
        db.close()


if __name__ == "__main__":
    main(*sys.argv[1:2])
