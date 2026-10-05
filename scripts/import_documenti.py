"""
One-off bootstrap import: read the school's real PDF documents and populate
the app's database with the derived association data (docenti, classi,
assegnazioni docente<->classe, disponibilita settimanale, calendario
annuale) for scuola_id="sch_1" (this is a v1 single-tenant app - see
README.md).

Three input files, each covering a different piece (see specs.md 3.1 for the
calendar's own role):

1. Calendario annuale (PDF, "CALENDARIO AF ..."): the school-year calendar -
   holidays/closures, daily hours per year-group. Already handled by
   CalendarParser.parse_calendario_pdf (used elsewhere for the normal setup
   flow too).
2. Elenco docenti (PDF, "Elenco Aule ..."): one row per docente with their
   assigned aula/laboratorio. Gives the docenti roster (full names) - the
   weekly timetable below only has surnames. Note per the person who
   commissioned this script: classi/aule here are not shared, i.e. this is
   a roughly 1:1 docente<->aula mapping (a couple of specialized labs are a
   deliberate exception, shared between two docenti who use them at
   different times).
3. Orario settimanale di esempio (PDF, "Orario scolastico dal X al Y..."):
   one week's actual timetable - one column per classe (17 real classes,
   e.g. "II ELETTRICISTI"), one row per hour slot, cell = docente surname.
   This is the actual source of the docente<->classe associations (which
   classi a docente teaches) and of docente availability (the hours a
   docente is observed present that week - used as a first-pass weekly
   availability grid, on the reasoning that "teaching then" implies
   "at school then"; an admin can correct it later via the availability UI).

Explicitly NOT available from any of these documents, so left as
placeholders to correct later (per instruction: "predisponi e ignora il suo
valore" - set the structure up, ignore the actual value for now):
- Docente tipo (ASSUNTO/CONTRATTO): defaulted to ASSUNTO for every
  discovered docente. Printed in the summary for manual review.
- Materia (subject) per assegnazione: the timetable has no subject column,
  only docente initials, so every assegnazione uses one shared placeholder
  Materia ("Materia da definire").
- Ore annuali (MonteOreAnnuale.ore_totali) per docente<->classe<->materia:
  set to 0 for every assegnazione.

Re-running this script wipes and rebuilds every table scoped to
scuola_id="sch_1" from a fresh read of the 3 PDFs - it is meant to be
re-run whenever the source PDFs change, not to accumulate data across runs.

Usage:
    python -m scripts.import_documenti [documenti_dir]
    (documenti_dir defaults to ./Documenti relative to the repo root)
"""

import difflib
import logging
import sys
from datetime import date
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import Base, engine, SessionLocal  # noqa: E402
from app.domain.parser import CalendarParser, SchoolRosterParser, GIORNI_ORDINE  # noqa: E402
from app.models import (  # noqa: E402
    Scuola, Classe, Docente, Materia, Assegnazione, CalendarioAnnuale,
    MonteOreAnnuale, DisponibilitaSettimanale,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("import_documenti")

SCUOLA_ID = "sch_1"
SCUOLA_NOME = "Agenzia Formativa don Angelo Tedoldi"
ANNO_FORMATIVO = "2026-2027"
PLACEHOLDER_MATERIA_NOME = "Materia da definire"
PLACEHOLDER_TIPO_DOCENTE = "ASSUNTO"

MESI_ITALIANI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}


def _find_default_files(documenti_dir: Path) -> Dict[str, Path]:
    files = {"calendario": None, "elenco_docenti": None, "orario_settimanale": None}
    for p in documenti_dir.glob("*.pdf"):
        lower = p.name.lower()
        if "calendario annuale" in lower or lower.startswith("cal"):
            files["calendario"] = p
        elif "elenco" in lower or "aule" in lower:
            files["elenco_docenti"] = p
        elif "orario" in lower or "calendario" in lower:
            files["orario_settimanale"] = p
    missing = [k for k, v in files.items() if v is None]
    if missing:
        raise FileNotFoundError(
            f"Could not find a PDF for: {missing} in {documenti_dir}. "
            f"Files found: {[p.name for p in documenti_dir.glob('*.pdf')]}"
        )
    return files


def _resolve_week_start(week_label: Optional[str], calendario_entries: list) -> Optional[date]:
    """
    week_label looks like "dal 14 al 18 Settembre" with no year. Find the
    year by matching the first day+month against the already-parsed annual
    calendar's actual dates.
    """
    if not week_label:
        return None
    import re
    m = re.search(r"dal\s+(\d{1,2})\s+al\s+\d{1,2}\s+(\w+)", week_label, re.IGNORECASE)
    if not m:
        return None
    day = int(m.group(1))
    month = MESI_ITALIANI.get(m.group(2).lower())
    if not month:
        return None
    for entry in calendario_entries:
        d = entry["data"]
        if d.day == day and d.month == month:
            return d
    return None


def _match_cognome(cognome: str, known_cognomi: set) -> str:
    """Exact match, or the closest known surname (handles PDF typos like FRASSINI/FRASSINE)."""
    if cognome in known_cognomi:
        return cognome
    close = difflib.get_close_matches(cognome, known_cognomi, n=1, cutoff=0.8)
    if close:
        logger.warning(f"Surname '{cognome}' not in roster, matched to closest '{close[0]}'")
        return close[0]
    logger.warning(f"Surname '{cognome}' not in roster and no close match - creating a bare docente for it")
    return cognome


def main(documenti_dir: Optional[str] = None) -> None:
    repo_root = Path(__file__).resolve().parent.parent
    dir_path = Path(documenti_dir) if documenti_dir else repo_root / "Documenti"
    if not dir_path.is_dir():
        raise FileNotFoundError(f"Documenti directory not found: {dir_path}")

    files = _find_default_files(dir_path)
    logger.info(f"Using files: { {k: v.name for k, v in files.items()} }")

    calendario_entries = CalendarParser.parse_calendario_pdf(files["calendario"].read_bytes())
    docenti_roster = SchoolRosterParser.parse_elenco_docenti_pdf(files["elenco_docenti"].read_bytes())
    orario = SchoolRosterParser.parse_orario_settimanale_pdf(files["orario_settimanale"].read_bytes())

    week_start = _resolve_week_start(orario["week_label"], calendario_entries)
    if week_start:
        logger.info(f"Weekly timetable resolved to week_start={week_start} (label: {orario['week_label']!r})")
    else:
        logger.warning(
            f"Could not resolve a year for week_label={orario['week_label']!r} against the "
            f"annual calendar - docente availability will NOT be saved."
        )

    # ---- Reconcile timetable surnames against the roster's full names -----
    roster_by_cognome = {d["cognome"]: d for d in docenti_roster}
    known_cognomi = set(roster_by_cognome)

    docente_classi: Dict[str, set] = {}  # cognome -> {classe_nome, ...}
    docente_ore_per_giorno: Dict[str, Dict[str, set]] = {}  # cognome -> giorno -> {ora_inizio,...}

    for slot in orario["slots"]:
        cognome = _match_cognome(slot["docente_cognome"], known_cognomi)
        docente_classi.setdefault(cognome, set()).add(slot["classe_nome"])
        docente_ore_per_giorno.setdefault(cognome, {}).setdefault(slot["giorno"], set()).add(slot["ora_inizio"])

    all_cognomi = known_cognomi | set(docente_classi)
    unreviewed_tipo = sorted(all_cognomi)
    unused_roster_entries = sorted(known_cognomi - set(docente_classi))

    # ---- Write to DB --------------------------------------------------
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        logger.info(f"Wiping existing data for scuola_id={SCUOLA_ID} before re-import")
        db.query(MonteOreAnnuale).filter_by(scuola_id=SCUOLA_ID).delete()
        db.query(Assegnazione).filter_by(scuola_id=SCUOLA_ID).delete()
        db.query(DisponibilitaSettimanale).filter_by(scuola_id=SCUOLA_ID).delete()
        db.query(CalendarioAnnuale).filter_by(scuola_id=SCUOLA_ID).delete()
        db.query(Materia).filter_by(scuola_id=SCUOLA_ID).delete()
        db.query(Classe).filter_by(scuola_id=SCUOLA_ID).delete()
        db.query(Docente).filter_by(scuola_id=SCUOLA_ID).delete()
        db.flush()

        anno_dates = [e["data"] for e in calendario_entries]
        scuola = Scuola(
            id=SCUOLA_ID,
            nome=SCUOLA_NOME,
            anno_formativo=ANNO_FORMATIVO,
            data_inizio_anno=min(anno_dates) if anno_dates else date.today(),
            data_fine_anno=max(anno_dates) if anno_dates else date.today(),
        )
        existing_scuola = db.query(Scuola).filter_by(id=SCUOLA_ID).first()
        if existing_scuola:
            existing_scuola.nome = scuola.nome
            existing_scuola.anno_formativo = scuola.anno_formativo
            existing_scuola.data_inizio_anno = scuola.data_inizio_anno
            existing_scuola.data_fine_anno = scuola.data_fine_anno
        else:
            db.add(scuola)
        db.flush()

        for entry in calendario_entries:
            db.add(CalendarioAnnuale(
                scuola_id=SCUOLA_ID,
                data=entry["data"],
                gruppo=entry.get("gruppo"),
                ore_max_giornata=entry["ore_max_giornata"],
                flag_chiusura=entry.get("flag_chiusura", False),
                flag_stage_classe_id=None,
                flag_stage_gruppo=entry.get("flag_stage_gruppo", False),
            ))
        logger.info(f"Calendario: {len(calendario_entries)} righe")

        classe_id_by_nome = {}
        for c in orario["classi"]:
            classe = Classe(scuola_id=SCUOLA_ID, nome=c["nome"], gruppo=c["gruppo"], n_studenti=0)
            db.add(classe)
            db.flush()
            classe_id_by_nome[c["nome"]] = classe.id
        logger.info(f"Classi: {len(classe_id_by_nome)}")

        docente_id_by_cognome = {}
        for cognome in sorted(all_cognomi):
            roster_entry = roster_by_cognome.get(cognome)
            nome = roster_entry["nome_completo"] if roster_entry else cognome
            docente = Docente(
                scuola_id=SCUOLA_ID,
                nome=nome,
                email=None,
                tipo=PLACEHOLDER_TIPO_DOCENTE,
                first_time_this_year=True,
            )
            db.add(docente)
            db.flush()
            docente_id_by_cognome[cognome] = docente.id
        logger.info(f"Docenti: {len(docente_id_by_cognome)}")

        materia = Materia(
            scuola_id=SCUOLA_ID, nome=PLACEHOLDER_MATERIA_NOME, tipo="TEORIA", peso_cognitivo="MEDIO",
        )
        db.add(materia)
        db.flush()

        n_assegnazioni = 0
        for cognome, classi_nomi in docente_classi.items():
            docente_id = docente_id_by_cognome[cognome]
            for classe_nome in classi_nomi:
                classe_id = classe_id_by_nome.get(classe_nome)
                if not classe_id:
                    continue
                db.add(Assegnazione(
                    scuola_id=SCUOLA_ID, docente_id=docente_id, classe_id=classe_id, materia_id=materia.id,
                ))
                db.add(MonteOreAnnuale(
                    scuola_id=SCUOLA_ID, classe_id=classe_id, materia_id=materia.id, docente_id=docente_id,
                    ore_totali=0, ore_erogate=0,
                ))
                n_assegnazioni += 1
        logger.info(f"Assegnazioni docente<->classe: {n_assegnazioni} (ore_totali=0 placeholder)")

        n_disponibilita = 0
        if week_start:
            for cognome, ore_per_giorno in docente_ore_per_giorno.items():
                docente_id = docente_id_by_cognome[cognome]
                giorni_fasce = {}
                for giorno in GIORNI_ORDINE:
                    ore_presenti = ore_per_giorno.get(giorno, set())
                    giorni_fasce[giorno] = [
                        {
                            "ora_inizio": f"{h:02d}:00",
                            "ora_fine": f"{h + 1:02d}:00",
                            "disponibile": h in ore_presenti,
                        }
                        for h in range(8, 14)
                    ]
                db.add(DisponibilitaSettimanale(
                    scuola_id=SCUOLA_ID, docente_id=docente_id, settimana_inizio=week_start,
                    giorni_fasce=giorni_fasce,
                ))
                n_disponibilita += 1
        logger.info(f"Disponibilita settimanali create: {n_disponibilita}")

        db.commit()

    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # ---- Summary --------------------------------------------------------
    print("\n=== Import completato ===")
    print(f"Scuola: {SCUOLA_NOME} (id={SCUOLA_ID})")
    print(f"Calendario: {len(calendario_entries)} righe")
    print(f"Classi: {len(classe_id_by_nome)}")
    print(f"Docenti: {len(docente_id_by_cognome)}")
    print(f"Assegnazioni docente<->classe: {n_assegnazioni}")
    print(f"Disponibilita settimanali: {n_disponibilita}"
          + ("" if week_start else " (SALTATE: anno non risolto per la settimana d'esempio)"))
    print(f"\nDA RIVEDERE MANUALMENTE:")
    print(f" - tipo ASSUNTO/CONTRATTO impostato di default per tutti i {len(unreviewed_tipo)} docenti "
          f"(non disponibile nei PDF): {', '.join(unreviewed_tipo)}")
    print(f" - ore annuali (monte ore) impostate a 0 per tutte le {n_assegnazioni} assegnazioni "
          f"(non disponibili nei PDF)")
    print(f" - materia placeholder unica '{PLACEHOLDER_MATERIA_NOME}' per tutte le assegnazioni "
          f"(il PDF orario non indica la materia)")
    if unused_roster_entries:
        print(f" - docenti nell'elenco aule ma senza ore nella settimana d'esempio "
              f"(nessuna assegnazione creata per loro): {', '.join(unused_roster_entries)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
