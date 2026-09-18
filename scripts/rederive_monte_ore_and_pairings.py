"""
Replaces the random-bucket MonteOreAnnuale.ore_totali simulation from
scripts/simulate_monte_ore.py with real weekly-hour counts, and (re)computes
ClasseAccoppiata rows for real class pairings - both derived by re-parsing
Documenti/es_di_calendario.pdf ("Orario scolastico dal 14 al 18 Settembre",
the same file scripts/import_documenti.py used to build docente<->classe
associations and availability, but without keeping the per-(docente,classe)
hour COUNT or the per-hour co-occurrence pattern that PDF's grid actually
has).

Why the ore_totali re-derivation: the random-bucket simulation left the
generated schedule full of empty "Libera" cells - it had no relationship to
how the real week is actually structured. The PDF's grid is a real,
once-published, ~96%-full timetable (472/493 classroom-hours - Friday runs
5h instead of 6h for every group, per scuola.calendario_annuale). Re-deriving
ore_totali from its actual per-(docente,classe) weekly hour count gives the
solver's per-week soft target (ore_residue // weeks_remaining, see
app/domain/solver.py) numbers that are structurally capable of
reconstructing that same near-full grid.

ore_totali is set to the RESIDUAL need from today to scuola.data_fine_anno
(weekly hour count x weeks remaining), not the full-year total - no docente
has an ore_erogate history to subtract from a full-year figure (every
existing OrarioSettimanale is still BOZZA, not a record of hours actually
delivered), so the residual has to be the figure this script produces
directly. Each docente of a given classe keeps their own distinct weekly
hour count, so their residuals differ from each other too; summed back up
per classe they land on exactly (that classe's total weekly hours) x weeks
remaining - the hours that classe has left to do this year. Re-running this
script later (e.g. after ore_erogate starts being tracked, or simply to
refresh the residual as weeks pass) is safe: it always recomputes from
scratch rather than accumulating.

Why per-docente pairings, not per-class-pair (school confirmed 2026-09-16
after the first version of this script got it wrong): a class pairing is
only real for the SPECIFIC docente(i) actually observed running the joint
lesson - most of a paired class's day is still ordinary, independent
lessons with its *other* docenti, who just also happen to have a separate
assegnazione to the paired class at some unrelated hour (that's normal, not
a pairing). The only reliable signal is two classes sharing the exact same
docente at the exact same (giorno, ora) cell in the PDF - a person can't be
in two rooms at once, so that can only be one merged/joint lesson, however
many times a week it happens (unlike class-pair-level co-occurrence counts,
a single instance is already solid evidence for a docente-level pairing -
no threshold needed). Per docente, every classe they were ever seen jointly
teaching this way (could be more than 2 - the school confirmed all four
"IV" year classes are always combined as one group, not pairs of 2 - one
docente turned out to only ever join 2 of those 4, so is paired on just
that one pair) becomes one ClasseAccoppiata row per pair within that
docente's own joint-classi set, naming that docente - see ClasseAccoppiata's
docstring in app/models.py. app/domain/solver.py's _constraint_paired_classes
and _paired_assignment_pair then only constrain that one named docente's own
assegnazione on each side, leaving every other docente of those classes
independent.

Usage:
    python -m scripts.rederive_monte_ore_and_pairings [scuola_id]
"""

import difflib
import sys
from collections import Counter, defaultdict
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Dict, FrozenSet, Optional, Set

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal  # noqa: E402
from app.domain.parser import SchoolRosterParser  # noqa: E402
from app.models import Classe, ClasseAccoppiata, Docente, Materia, MonteOreAnnuale, Scuola  # noqa: E402

PDF_PATH = Path(__file__).resolve().parent.parent / "Documenti" / "es_di_calendario.pdf"


def _resolve_cognome(cognome: str, known_cognomi: Set[str]) -> Optional[str]:
    if cognome in known_cognomi:
        return cognome
    close = difflib.get_close_matches(cognome, known_cognomi, n=1, cutoff=0.8)
    return close[0] if close else None


def main(scuola_id: str = "sch_1") -> None:
    data = SchoolRosterParser.parse_orario_settimanale_pdf(PDF_PATH.read_bytes())
    slots = data["slots"]

    db = SessionLocal()
    try:
        scuola = db.query(Scuola).filter_by(id=scuola_id).first()
        weeks_remaining = max(1, round((scuola.data_fine_anno - date.today()).days / 7))

        docenti = db.query(Docente).filter_by(scuola_id=scuola_id).all()
        docente_id_by_cognome: Dict[str, str] = {}
        known_cognomi: Set[str] = set()
        for d in docenti:
            cognome = d.nome.strip().split()[0].upper()
            docente_id_by_cognome[cognome] = d.id
            known_cognomi.add(cognome)

        classi = db.query(Classe).filter_by(scuola_id=scuola_id).all()
        classe_id_by_nome = {c.nome: c.id for c in classi}
        gruppo_by_nome = {c.nome: c.gruppo for c in classi}

        materia = db.query(Materia).filter_by(scuola_id=scuola_id).first()

        # Resolve every slot's cognome once, reused below for both ore_totali
        # and pairings.
        resolved_slots = []
        unmatched_cognomi: Set[str] = set()
        for s in slots:
            cognome = _resolve_cognome(s["docente_cognome"], known_cognomi)
            if not cognome:
                unmatched_cognomi.add(s["docente_cognome"])
                continue
            resolved_slots.append({**s, "docente_cognome": cognome})
        if unmatched_cognomi:
            print(f"WARNING: {len(unmatched_cognomi)} surnames in the PDF matched no docente: "
                  f"{sorted(unmatched_cognomi)}")

        # ---- Real weekly hours per (docente, classe) ------------------
        weekly_hours = defaultdict(set)  # (docente_id, classe_id) -> {(giorno, ora), ...}
        for s in resolved_slots:
            classe_id = classe_id_by_nome.get(s["classe_nome"])
            docente_id = docente_id_by_cognome.get(s["docente_cognome"])
            if not classe_id or not docente_id:
                continue
            weekly_hours[(docente_id, classe_id)].add((s["giorno"], s["ora_inizio"]))

        n_updated, n_created, total_residual_hours = 0, 0, 0
        for (docente_id, classe_id), cells in weekly_hours.items():
            ore_totali = len(cells) * weeks_remaining
            total_residual_hours += ore_totali
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
              f"(weeks_remaining={weeks_remaining}, total residual hours={total_residual_hours}).")

        # ---- Pairings, per docente (see module docstring) -----------------
        by_cell = defaultdict(set)
        for s in resolved_slots:
            by_cell[(s["giorno"], s["ora_inizio"], s["docente_cognome"])].add(s["classe_nome"])

        # A co-occurrence cell naming MORE than 2 classi is trustworthy only
        # if that exact group recurs consistently (school confirmed only one
        # such group exists: all four "IV" year classes, always combined) -
        # aggregated across every docente who has it. A size->2 group seen
        # only once, or that doesn't match that one stable group, is almost
        # certainly two unrelated pairs whose cells coincidentally landed on
        # the same (giorno, ora) key (e.g. two adjacent sub-tables in the PDF
        # merging at a row boundary) - not a real multi-way pairing. Verified
        # against this school's PDF: every such one-off blob turned out to be
        # the union of two pairs that are ALSO independently confirmed on
        # their own elsewhere, so discarding it loses no real signal.
        group_totals: Counter = Counter()
        for classi_nomi in by_cell.values():
            if len(classi_nomi) > 2:
                group_totals[frozenset(classi_nomi)] += 1
        canonical_supergroup: Optional[FrozenSet[str]] = (
            max(group_totals, key=group_totals.get) if group_totals else None
        )
        if len(group_totals) > 1:
            print(f"NOTA: {len(group_totals) - 1} gruppi >2 classi scartati come rumore "
                  f"(non il gruppo stabile {sorted(canonical_supergroup)}): "
                  f"{[sorted(g) for g in group_totals if g != canonical_supergroup]}")

        def _same_gruppo(names: Set[str]) -> bool:
            gruppi = {gruppo_by_nome.get(n) for n in names}
            return len(gruppi) == 1 and None not in gruppi

        docente_joint_groups: Dict[str, Set[FrozenSet[str]]] = defaultdict(set)
        n_cross_gruppo_dropped = 0
        for (_giorno, _ora, cognome), classi_nomi in by_cell.items():
            group = frozenset(classi_nomi)
            if len(group) != 2 and group != canonical_supergroup:
                continue
            # A pairing only ever happens within the same year group (PRIME/
            # SECONDE/TERZE/QUARTE) in this school - same track across years
            # (e.g. "II OP. INFORM." with "III OP. INFORM.") is a one-off
            # coincidence (a substitute teacher, most likely), not a real
            # pairing, however clean the co-occurrence cell looks.
            if not _same_gruppo(classi_nomi):
                n_cross_gruppo_dropped += 1
                continue
            docente_joint_groups[cognome].add(group)
        if n_cross_gruppo_dropped:
            print(f"NOTA: {n_cross_gruppo_dropped} celle scartate perché tra classi di anni diversi "
                  f"(mai un vero accoppiamento in questa scuola).")

        # This script is meant to be re-run whenever the source PDF or this
        # logic changes, not to accumulate stale rows from earlier runs.
        n_deleted = db.query(ClasseAccoppiata).filter_by(scuola_id=scuola_id, materia_id=materia.id).delete()

        n_pairings = 0
        for cognome, groups in sorted(docente_joint_groups.items()):
            docente_id = docente_id_by_cognome.get(cognome)
            if not docente_id:
                continue
            pairs_done: Set[FrozenSet[str]] = set()
            for group in groups:
                for a, b in combinations(sorted(group), 2):
                    if frozenset((a, b)) in pairs_done:
                        continue
                    pairs_done.add(frozenset((a, b)))
                    classe_a_id = classe_id_by_nome.get(a)
                    classe_b_id = classe_id_by_nome.get(b)
                    if not classe_a_id or not classe_b_id:
                        continue
                    db.add(ClasseAccoppiata(
                        scuola_id=scuola_id, classe_a_id=classe_a_id, classe_b_id=classe_b_id,
                        materia_id=materia.id, docente_id=docente_id,
                        note=f"{cognome} rilevato in compresenza su {a} e {b} (es_di_calendario.pdf)",
                    ))
                    n_pairings += 1
                    print(f"  {cognome}: {a} <-> {b}")
        db.commit()
        print(f"ClasseAccoppiata: {n_deleted} righe precedenti rimosse, {n_pairings} nuove create.")
    finally:
        db.close()


if __name__ == "__main__":
    main(*sys.argv[1:2])
