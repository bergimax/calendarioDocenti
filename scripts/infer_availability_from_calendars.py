"""
One-off test: infer CONTRATTO docente availability from the two real weekly
timetable PDFs in Documenti/ (es_di_calendario.pdf, "dal 14 al 18 Settembre
2026", and es_di_calendario_2.pdf, "dal 21 al 25 Settembre 2026" - both
already-published real weeks, not simulated data), and use that to generate
the next week's OrarioSettimanale.

Unlike scripts/set_contratto_availability.py (which had only ONE real week
on file and had to fall back to a fixed-seed random day-pattern simulation),
this has TWO independent real weeks, so a docente's actual availability can
be derived directly: for each (giorno, ora) cell, the docente is available
if they were observed teaching ANY class at that cell in EITHER week (a
positive observation is solid evidence of availability; a week where they
happen not to be scheduled at a given hour isn't evidence they're
unavailable then - the other week having them there settles it). No random
guessing involved - only touches CONTRATTO docenti, same as
set_contratto_availability.py, since ASSUNTO availability is never enforced
by the solver (app/domain/solver.py's _constraint_teacher_availability).

A docente with zero observed hours in both PDFs (no signal at all) falls
back to their most recently recorded DisponibilitaSettimanale row instead of
being marked unavailable all week (which would force the solver to either
override their whole week or go infeasible - see that constraint's
docstring).

Writes DisponibilitaSettimanale for the next week that doesn't already have
an OrarioSettimanale (computed from today, not hardcoded), then runs
ScheduleService.generate_schedule for that week and prints the result.

Usage:
    python -m scripts.infer_availability_from_calendars [scuola_id]
"""

import difflib
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.domain.parser import GIORNI_ORDINE, SchoolRosterParser  # noqa: E402
from app.models import Docente, DisponibilitaSettimanale, OrarioSettimanale  # noqa: E402
from app.services.schedule import ScheduleService  # noqa: E402

DOCUMENTI_DIR = Path(__file__).resolve().parent.parent / "Documenti"
PDF_PATHS = [DOCUMENTI_DIR / "es_di_calendario.pdf", DOCUMENTI_DIR / "es_di_calendario_2.pdf"]
ORE_GIORNO = list(range(8, 14))  # 08:00-14:00


def _resolve_cognome(cognome: str, known_cognomi: Set[str]) -> Optional[str]:
    if cognome in known_cognomi:
        return cognome
    close = difflib.get_close_matches(cognome, known_cognomi, n=1, cutoff=0.8)
    return close[0] if close else None


def _next_ungenerated_monday(db, scuola_id: str) -> date:
    today = date.today()
    monday_this_week = today - timedelta(days=today.weekday())
    candidate = monday_this_week + timedelta(days=7)
    existing = {
        row[0] for row in db.query(OrarioSettimanale.settimana_inizio)
        .filter_by(scuola_id=scuola_id).all()
    }
    while candidate in existing:
        candidate += timedelta(days=7)
    return candidate


def main(scuola_id: str = "sch_1") -> None:
    weekly_cells_by_pdf = []
    for pdf_path in PDF_PATHS:
        data = SchoolRosterParser.parse_orario_settimanale_pdf(pdf_path.read_bytes())
        print(f"Parsed {pdf_path.name}: week {data['week_label']!r}, {len(data['slots'])} slot entries")
        weekly_cells_by_pdf.append(data["slots"])

    db = SessionLocal()
    try:
        docenti = db.query(Docente).filter_by(scuola_id=scuola_id).all()
        cognome_by_id = {d.id: d.nome.strip().split()[0].upper() for d in docenti}
        known_cognomi = set(cognome_by_id.values())
        contratto = [d for d in docenti if d.tipo == "CONTRATTO"]

        weekly_cells: Dict[str, Set[Tuple[str, int]]] = {}
        for slots in weekly_cells_by_pdf:
            for s in slots:
                cognome = _resolve_cognome(s["docente_cognome"], known_cognomi)
                if not cognome:
                    continue
                weekly_cells.setdefault(cognome, set()).add((s["giorno"], s["ora_inizio"]))

        target_week = _next_ungenerated_monday(db, scuola_id)
        print(f"\nTarget week for generation: {target_week}")

        n_from_observation, n_from_fallback = 0, 0
        for d in contratto:
            cognome = cognome_by_id[d.id]
            cells = weekly_cells.get(cognome, set())

            if cells:
                giorni_fasce = {
                    giorno: [
                        {
                            "ora_inizio": f"{h:02d}:00",
                            "ora_fine": f"{h + 1:02d}:00",
                            "disponibile": (giorno, h) in cells,
                        }
                        for h in ORE_GIORNO
                    ]
                    for giorno in GIORNI_ORDINE
                }
                n_from_observation += 1
                n_hours = len(cells)
                n_days = len({g for g, _ in cells})
                print(f"  {d.nome}: {n_hours}h observed across {n_days} giorni (union of both weeks)")
            else:
                prev = (
                    db.query(DisponibilitaSettimanale)
                    .filter_by(scuola_id=scuola_id, docente_id=d.id)
                    .order_by(DisponibilitaSettimanale.settimana_inizio.desc())
                    .first()
                )
                if not prev:
                    print(f"  {d.nome}: NOT observed in either PDF and no prior availability on file - skipping")
                    continue
                giorni_fasce = prev.giorni_fasce
                n_from_fallback += 1
                print(f"  {d.nome}: NOT observed in either PDF - carried forward from {prev.settimana_inizio}")

            row = db.query(DisponibilitaSettimanale).filter_by(
                scuola_id=scuola_id, docente_id=d.id, settimana_inizio=target_week,
            ).first()
            if row:
                row.giorni_fasce = giorni_fasce
            else:
                db.add(DisponibilitaSettimanale(
                    scuola_id=scuola_id, docente_id=d.id, settimana_inizio=target_week,
                    giorni_fasce=giorni_fasce,
                ))

        db.commit()
        print(
            f"\nDisponibilitaSettimanale for {target_week}: {n_from_observation} docenti from real "
            f"observation, {n_from_fallback} from fallback (prior week)."
        )

        print(f"\nGenerating schedule for {target_week} ...")
        result = ScheduleService(db).generate_schedule(scuola_id, target_week, timeout_seconds=120)

        print(f"\nstatus: {result.status}")
        if result.status in ("generated",):
            n_slots = len(result.slots) if result.slots else 0
            print(f"schedule_id: {result.schedule_id}")
            print(f"quality_score: {result.quality_score}  quality_level: {result.quality_level}")
            print(f"n_slots generated: {n_slots}")
        else:
            print(f"message: {result.message}")
            if getattr(result, "conflicting_constraints", None):
                print(f"conflicting_constraints: {result.conflicting_constraints}")
            if getattr(result, "suggested_deroghe", None):
                print(f"suggested_deroghe: {result.suggested_deroghe}")
    finally:
        db.close()


if __name__ == "__main__":
    main(*sys.argv[1:2])
