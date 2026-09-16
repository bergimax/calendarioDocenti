"""
Replaces the random-bucket MonteOreAnnuale.ore_totali simulation from
scripts/simulate_monte_ore.py with real weekly-hour counts, and adds the
ClasseAccoppiata rows for real class pairings - both derived by re-parsing
Documenti/es_di_calendario.pdf ("Orario scolastico dal 14 al 18 Settembre",
the same file scripts/import_documenti.py used to build docente<->classe
associations and availability, but without keeping the per-(docente,classe)
hour COUNT that PDF's grid actually has).

Why: the random-bucket simulation left the generated schedule full of empty
"Libera" cells - it had no relationship to how the real week is actually
structured, so there was no reason it should ever sum to fill a class's
whole day. The PDF's grid is a real, once-published, ~90-93%-full timetable
(each class is filled 27-28 of its ~29-30 weekly hour slots, per
scuola.calendario_annuale - Friday runs 5h instead of 6h for every group).
Re-deriving ore_totali from its actual per-(docente,classe) weekly hour
count, annualized (x weeks_in_year), gives the solver's per-week soft
target (ore_residue // weeks_in_year, see app/domain/solver.py) numbers
that are structurally capable of reconstructing that same near-full grid.

Pairings: grouping the PDF's slots by (giorno, ora_inizio, docente_cognome)
and looking for cells where more than one classe shares the same docente at
the same hour surfaces which classes are actually taught together. A few
pairs (2 occurrences across the week) are almost certainly incidental
(a substitute covering two classes once); the real, consistently recurring
pairs (14-22 occurrences, i.e. nearly every one of that pair's hours) are
kept, threshold >=10. One is a 4-way group (all four IV year classes) -
ClasseAccoppiata only models 2 classes at a time, so it's recorded as a
3-pair chain (A-B, B-C, C-D), which forces all four equal transitively via
_constraint_paired_classes the same as recording all 6 pairs would.

Usage:
    python -m scripts.rederive_monte_ore_and_pairings [scuola_id]
"""

import difflib
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.domain.parser import SchoolRosterParser  # noqa: E402
from app.models import Classe, ClasseAccoppiata, Docente, Materia, MonteOreAnnuale, Scuola  # noqa: E402

PDF_PATH = Path(__file__).resolve().parent.parent / "Documenti" / "es_di_calendario.pdf"
PAIRING_MIN_OCCURRENCES = 10


def main(scuola_id: str = "sch_1") -> None:
    data = SchoolRosterParser.parse_orario_settimanale_pdf(PDF_PATH.read_bytes())
    slots = data["slots"]

    db = SessionLocal()
    try:
        scuola = db.query(Scuola).filter_by(id=scuola_id).first()
        weeks_in_year = max(1, round((scuola.data_fine_anno - scuola.data_inizio_anno).days / 7))

        docenti = db.query(Docente).filter_by(scuola_id=scuola_id).all()
        docente_id_by_cognome = {}
        known_cognomi = set()
        for d in docenti:
            cognome = d.nome.strip().split()[0].upper()
            docente_id_by_cognome[cognome] = d.id
            known_cognomi.add(cognome)

        classi = db.query(Classe).filter_by(scuola_id=scuola_id).all()
        classe_id_by_nome = {c.nome: c.id for c in classi}

        materia = db.query(Materia).filter_by(scuola_id=scuola_id).first()

        # ---- Real weekly hours per (docente, classe) ------------------
        weekly_hours = defaultdict(set)  # (docente_id, classe_id) -> {(giorno, ora), ...}
        unmatched_cognomi = set()
        for s in slots:
            cognome = s["docente_cognome"]
            if cognome not in known_cognomi:
                close = difflib.get_close_matches(cognome, known_cognomi, n=1, cutoff=0.8)
                if not close:
                    unmatched_cognomi.add(cognome)
                    continue
                cognome = close[0]
            classe_id = classe_id_by_nome.get(s["classe_nome"])
            docente_id = docente_id_by_cognome.get(cognome)
            if not classe_id or not docente_id:
                continue
            weekly_hours[(docente_id, classe_id)].add((s["giorno"], s["ora_inizio"]))
        if unmatched_cognomi:
            print(f"WARNING: {len(unmatched_cognomi)} surnames in the PDF matched no docente: "
                  f"{sorted(unmatched_cognomi)}")

        n_updated, n_created, total_annual_hours = 0, 0, 0
        for (docente_id, classe_id), cells in weekly_hours.items():
            ore_totali = len(cells) * weeks_in_year
            total_annual_hours += ore_totali
            row = db.query(MonteOreAnnuale).filter_by(
                scuola_id=scuola_id, docente_id=docente_id, classe_id=classe_id, materia_id=materia.id,
            ).first()
            if row:
                row.ore_totali = ore_totali
                row.ore_erogate = 0
                n_updated += 1
            else:
                db.add(MonteOreAnnuale(
                    scuola_id=scuola_id, docente_id=docente_id, classe_id=classe_id, materia_id=materia.id,
                    ore_totali=ore_totali, ore_erogate=0,
                ))
                n_created += 1
        db.commit()
        print(f"MonteOreAnnuale: {n_updated} updated, {n_created} created "
              f"(weeks_in_year={weeks_in_year}, total annual hours={total_annual_hours}).")

        # ---- Pairings ---------------------------------------------------
        by_cell = defaultdict(set)
        for s in slots:
            by_cell[(s["giorno"], s["ora_inizio"], s["docente_cognome"])].add(s["classe_nome"])

        pair_counts = defaultdict(int)
        for classi_nomi in by_cell.values():
            if len(classi_nomi) < 2:
                continue
            names = sorted(classi_nomi)
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    pair_counts[(names[i], names[j])] += 1

        # Group real pairs into connected components (handles the 4-way case).
        real_pairs = {p for p, cnt in pair_counts.items() if cnt >= PAIRING_MIN_OCCURRENCES}
        adjacency = defaultdict(set)
        for a, b in real_pairs:
            adjacency[a].add(b)
            adjacency[b].add(a)

        seen = set()
        n_pairings = 0
        for start in list(adjacency):
            if start in seen:
                continue
            # BFS to collect this connected component, then chain it A-B-C-D.
            component, queue = [], [start]
            while queue:
                node = queue.pop()
                if node in seen:
                    continue
                seen.add(node)
                component.append(node)
                queue.extend(adjacency[node] - seen)
            for a, b in zip(component, component[1:]):
                classe_a_id = classe_id_by_nome.get(a)
                classe_b_id = classe_id_by_nome.get(b)
                if not classe_a_id or not classe_b_id:
                    continue
                exists = db.query(ClasseAccoppiata).filter_by(
                    scuola_id=scuola_id, classe_a_id=classe_a_id, classe_b_id=classe_b_id, materia_id=materia.id,
                ).first() or db.query(ClasseAccoppiata).filter_by(
                    scuola_id=scuola_id, classe_a_id=classe_b_id, classe_b_id=classe_a_id, materia_id=materia.id,
                ).first()
                if exists:
                    continue
                db.add(ClasseAccoppiata(
                    scuola_id=scuola_id, classe_a_id=classe_a_id, classe_b_id=classe_b_id, materia_id=materia.id,
                    note=f"Rilevato da es_di_calendario.pdf ({pair_counts.get((a, b), pair_counts.get((b, a)))} "
                         f"occorrenze su 30 ore settimanali)",
                ))
                n_pairings += 1
                print(f"  Accoppiamento: {a} <-> {b}")
        db.commit()
        print(f"ClasseAccoppiata: {n_pairings} righe create.")
    finally:
        db.close()


if __name__ == "__main__":
    main(*sys.argv[1:2])
