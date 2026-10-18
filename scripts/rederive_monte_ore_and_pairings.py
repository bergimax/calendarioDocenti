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
(weekly hour count x weeks with lessons remaining: closures/stage/0-hour days excluded), not the full-year total - no docente
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

Model: since 2026-10-07 an assegnazione is docente + classe + tipo ("In coppia" / "Singola", held in
the materia_id column, see app/services/tipo_lezione.py). The joint cells found per docente are the
"In coppia" monte ore (counted once per group, same value for every classe of the group); the
docente's remaining cells with a classe are its "Singola" monte ore. Only existing assegnazioni get
a monte ore. ore_totali = residual need (weekly hours x weeks with lessons, closures/stage excluded)
PLUS the ore_erogate already delivered, which is never reset: re-running is safe on approved weeks.
Only pairings created by this script (note ends with the PDF name) are replaced; manual ones stay.

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
from app.models import (  # noqa: E402
    Assegnazione, CalendarioAnnuale, Classe, ClasseAccoppiata, Docente, MonteOreAnnuale, Scuola,
)
from app.services.tipo_lezione import tipo_materie  # noqa: E402

PDF_PATH = Path(__file__).resolve().parent.parent / "Documenti" / "es_di_calendario.pdf"


def _resolve_cognome(cognome: str, known_cognomi: Set[str]) -> Optional[str]:
    if cognome in known_cognomi:
        return cognome
    close = difflib.get_close_matches(cognome, known_cognomi, n=1, cutoff=0.8)
    return close[0] if close else None


def _settimane_utili(righe, gruppo: Optional[str], classe_id: str, fallback: int) -> float:
    """
    Remaining school weeks in which the classe really has lessons, as lesson days / 5 - same rule
    as SolverContext._settimane_utili in app/domain/solver.py: closures, 0-hour days and stage
    (classe or whole gruppo) don't count. Falls back to calendar weeks when there are no rows.
    """
    if not righe:
        return fallback
    per_data = {}
    for c in righe:
        if c.data.weekday() >= 5:
            continue
        if gruppo is not None and c.gruppo == gruppo:
            per_data[c.data] = c
        elif c.gruppo is None and c.data not in per_data:
            per_data[c.data] = c
    giorni = sum(
        1 for c in per_data.values()
        if not (c.flag_chiusura or c.ore_max_giornata == 0 or c.flag_stage_gruppo
                or c.flag_stage_classe_id == classe_id)
    )
    return max(giorni / 5, 1)


def main(scuola_id: str = "sch_1") -> None:
    data = SchoolRosterParser.parse_orario_settimanale_pdf(PDF_PATH.read_bytes())
    slots = data["slots"]

    db = SessionLocal()
    try:
        scuola = db.query(Scuola).filter_by(id=scuola_id).first()
        weeks_remaining = max(1, round((scuola.data_fine_anno - date.today()).days / 7))
        righe_calendario = db.query(CalendarioAnnuale).filter(
            CalendarioAnnuale.scuola_id == scuola_id,
            CalendarioAnnuale.data >= date.today(),
            CalendarioAnnuale.data <= scuola.data_fine_anno,
        ).all()

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
        gruppo_by_id = {c.id: c.gruppo for c in classi}

        coppia_id, singola_id = tipo_materie(db, scuola_id)

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

        docente_joint_groups: Dict[str, Dict[FrozenSet[str], Set]] = defaultdict(lambda: defaultdict(set))
        n_cross_gruppo_dropped = 0
        for (giorno, ora, cognome), classi_nomi in by_cell.items():
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
            docente_joint_groups[cognome][group].add((giorno, ora))
        if n_cross_gruppo_dropped:
            print(f"NOTA: {n_cross_gruppo_dropped} celle scartate perché tra classi di anni diversi "
                  f"(mai un vero accoppiamento in questa scuola).")

        # This script is meant to be re-run whenever the source PDF or this
        # logic changes, not to accumulate stale rows from earlier runs.
        # Only the rows this script created (note names the PDF): pairings the admin added by hand
        # are not in the PDF and must survive a re-run.
        n_deleted = db.query(ClasseAccoppiata).filter(
            ClasseAccoppiata.scuola_id == scuola_id,
            ClasseAccoppiata.note.like("%(es_di_calendario.pdf)"),
        ).delete(synchronize_session=False)
        manual = {
            (p.docente_id, frozenset((p.classe_a_id, p.classe_b_id)))
            for p in db.query(ClasseAccoppiata).filter_by(scuola_id=scuola_id).all()
        }

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
                    if (docente_id, frozenset((classe_a_id, classe_b_id))) in manual:
                        continue
                    db.add(ClasseAccoppiata(
                        scuola_id=scuola_id, classe_a_id=classe_a_id, classe_b_id=classe_b_id,
                        materia_id=coppia_id, docente_id=docente_id,
                        note=f"{cognome} rilevato in compresenza su {a} e {b} (es_di_calendario.pdf)",
                    ))
                    n_pairings += 1
                    print(f"  {cognome}: {a} <-> {b}")
        db.commit()
        print(f"ClasseAccoppiata: {n_deleted} righe precedenti rimosse, {n_pairings} nuove create.")

        # ---- Monte ore per (docente, classe, tipo) ------------------------
        # "In coppia": the joint cells of a docente's group, counted ONCE per group (one joint
        # lesson consumes the pair's monte ore once) and given to every classe of the group.
        # "Singola": the classe's remaining cells with that docente.
        # ore_totali = residual need (weekly hours x weeks with lessons) + ore_erogate already
        # delivered, so a re-run keeps the delivered hours and the residual stays today->fine anno.
        coppia_hours: Dict[tuple, int] = defaultdict(int)  # (docente_id, classe_id) -> weekly hours
        joint_cells: Dict[tuple, Set] = defaultdict(set)   # (docente_id, classe_id) -> cells
        for cognome, groups in docente_joint_groups.items():
            docente_id = docente_id_by_cognome.get(cognome)
            for group, cells in groups.items():
                for nome in group:
                    classe_id = classe_id_by_nome.get(nome)
                    if docente_id and classe_id:
                        coppia_hours[(docente_id, classe_id)] += len(cells)
                        joint_cells[(docente_id, classe_id)] |= cells
        singola_hours = {
            key: len(cells - joint_cells.get(key, set())) for key, cells in weekly_hours.items()
        }

        wanted = []  # (docente_id, classe_id, tipo_id, weekly_hours)
        wanted += [(d, c, coppia_id, h) for (d, c), h in coppia_hours.items() if h]
        wanted += [(d, c, singola_id, h) for (d, c), h in singola_hours.items() if h]
        have_asg = {
            (a.docente_id, a.classe_id, a.materia_id)
            for a in db.query(Assegnazione).filter_by(scuola_id=scuola_id).all()
        }
        n_updated, n_created, n_no_asg, total_residual_hours = 0, 0, 0, 0
        seen = set()
        for docente_id, classe_id, tipo_id, weekly in wanted:
            key = (docente_id, classe_id, tipo_id)
            if key not in have_asg:
                n_no_asg += 1  # the PDF names a lesson the school data has no assegnazione for
                continue
            seen.add(key)
            weeks_classe = _settimane_utili(
                righe_calendario, gruppo_by_id.get(classe_id), classe_id, weeks_remaining,
            )
            residual = round(weekly * weeks_classe)
            total_residual_hours += residual
            row = db.query(MonteOreAnnuale).filter_by(
                scuola_id=scuola_id, docente_id=docente_id, classe_id=classe_id, materia_id=tipo_id,
            ).first()
            if row:
                row.ore_totali = residual + (row.ore_erogate or 0)
                n_updated += 1
            else:
                db.add(MonteOreAnnuale(
                    scuola_id=scuola_id, docente_id=docente_id, classe_id=classe_id, materia_id=tipo_id,
                    ore_totali=residual, ore_erogate=0,
                ))
                n_created += 1
        untouched = len(have_asg - seen)
        db.commit()
        print(f"MonteOreAnnuale: {n_updated} updated, {n_created} created, {untouched} assegnazioni "
              f"not in the PDF left untouched, {n_no_asg} PDF lessons without assegnazione skipped "
              f"(weeks_remaining={weeks_remaining}, total residual hours={total_residual_hours}).")
    finally:
        db.close()


if __name__ == "__main__":
    main(*sys.argv[1:2])
