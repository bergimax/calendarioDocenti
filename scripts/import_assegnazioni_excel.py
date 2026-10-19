"""
Allinea Assegnazioni e monte ore al file Excel "orari docenti" (incarichi per docente/classe).

Ogni riga dell'Excel è (docente, classe o gruppo di classi, materia, ore). La materia non esiste
più nel modello: contano docente + classe + tipo.
- una riga con più classi ("I ESTE - I PAN", "TUTTE LE IV") è "In coppia": ogni classe del gruppo
  riceve le ore della riga (una lezione doppia consuma una sola volta il monte della coppia);
- una riga con una classe sola è "Singola";
- più righe con lo stesso docente + classe + tipo (materie diverse) si sommano.

Per ogni (docente, classe, tipo) risultante lo script verifica che l'assegnazione esista (e, per le
coppie, che la classe sia in un accoppiamento del docente), crea quel che manca e imposta
ore_totali. ore_erogate non si tocca. Non cancella nulla: ciò che nel DB non è nell'Excel viene
solo elencato.

Uso:
    python -m scripts.import_assegnazioni_excel FILE.xlsx            # simulazione
    python -m scripts.import_assegnazioni_excel FILE.xlsx --applica  # scrive sul DB
"""
import itertools
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Assegnazione, Classe, ClasseAccoppiata, Docente, MonteOreAnnuale  # noqa: E402
from app.services.tipo_lezione import gruppi_coppia, tipo_materie  # noqa: E402

ROMANI = {"I": 1, "II": 2, "III": 3, "IV": 4}
# parola chiave del nome sul foglio -> parola chiave del nome classe nel DB
INDIRIZZI = {"ESTE": "ESTET", "PAN": "PAN", "PANIF": "PAN", "PANIFICAZIONE": "PAN",
             "INFO": "INFORM", "ELE": "ELETTR", "ITC": "I.T.C."}
# Docenti di sostegno: seguono singoli allievi, non fanno parte dell'orario delle classi
ESCLUSI = ("CAPRETTI",)
NOTE = "Da Excel orari docenti AF 26/27"


def _anno_e_indirizzo(nome_db: str) -> Tuple[int, str]:
    anno, _, resto = nome_db.partition(" ")
    return ROMANI[anno], resto


def risolvi_classi(testo: str, classi_db: List[Classe], area: str = "") -> Optional[List[str]]:
    """ID delle classi nominate da `testo` (None se non riconosciuto)."""
    t = " ".join(testo.upper().split())
    if t in ("TUTTE LE IV", "IV ANNI"):
        anni = {4}
        return [c.id for c in classi_db if _anno_e_indirizzo(c.nome)[0] in anni]
    # "I INFO (4+2)" e "I ITC (4+2)" sono la classe I.T.C.
    t = re.sub(r"\s*\(4\+2\)", " (ITC)", t)
    # "I PAN" con area "(itc 4+2)": la materia è dell'I.T.C. (refuso del foglio)
    if "ITC" in area.upper() and t == "I PAN":
        t = "I ITC"
    ids = []
    for pezzo in re.split(r"\s*-\s*", t):
        m = re.match(r"^(I{1,3}|IV)\s+([A-Z]+)(?:\s*\(ITC\))?$", pezzo.strip())
        if not m:
            return None
        anno, ind = ROMANI[m.group(1)], m.group(2)
        if "(ITC)" in pezzo:
            ind = "ITC"
        chiave = INDIRIZZI.get(ind)
        trovate = [c for c in classi_db if _anno_e_indirizzo(c.nome)[0] == anno
                   and chiave and chiave in c.nome.upper()]
        if len(trovate) != 1:
            return None
        ids.append(trovate[0].id)
    return list(dict.fromkeys(ids))


def leggi_excel(path: str) -> List[Tuple[str, str, str, int, str]]:
    """[(cognome-nome del foglio, testo classe, area, ore, materia)] con docente/classe riportati
    dalle righe sopra quando la cella è vuota."""
    ws = openpyxl.load_workbook(path, data_only=True).active
    righe, docente, classe = [], None, None
    for a, nome, cl, area, materia, ore in ws.iter_rows(min_row=4, values_only=True):
        if nome and str(nome).strip():
            docente, classe = str(nome).strip(), None
        if cl and str(cl).strip():
            classe = str(cl).strip()
        if not materia or not isinstance(ore, (int, float)) or ore <= 0:
            continue  # intestazioni, totali, righe senza ore
        if docente and classe:
            righe.append((docente, classe, area or "", int(ore), str(materia).strip()))
    return righe


def trova_docente(nome_foglio: str, docenti: List[Docente]) -> Optional[Docente]:
    chiave = nome_foglio.upper().split()
    trovati = [d for d in docenti if d.nome.upper().split()[: len(chiave)] == chiave]
    return trovati[0] if len(trovati) == 1 else None


def main(path: str, applica: bool, scuola_id: str = "sch_1") -> None:
    db = SessionLocal()
    docenti = db.query(Docente).filter_by(scuola_id=scuola_id).all()
    classi = db.query(Classe).filter_by(scuola_id=scuola_id).all()
    nome_classe = {c.id: c.nome for c in classi}
    coppia_id, singola_id = tipo_materie(db, scuola_id)

    # (docente_id, classe_id, tipo) -> ore; gruppi richiesti per docente
    ore: Dict[Tuple[str, str, str], int] = defaultdict(int)
    gruppi: Dict[str, Set[frozenset]] = defaultdict(set)
    problemi: List[str] = []
    for nome, testo, area, n, materia in leggi_excel(path):
        if nome.upper().split()[0] in ESCLUSI:
            continue
        d = trova_docente(nome, docenti)
        ids = risolvi_classi(testo, classi, area)
        if not d or not ids:
            problemi.append(f"NON RICONOSCIUTO: {nome!r} / {testo!r} / {materia!r} ({n}h)")
            continue
        tipo = coppia_id if len(ids) > 1 else singola_id
        if len(ids) > 1:
            gruppi[d.id].add(frozenset(ids))
        for cid in ids:
            ore[(d.id, cid, tipo)] += n

    # accoppiamenti: una classe "in coppia" deve stare in un gruppo del docente
    nuovi_accoppiamenti = []
    divergenze = []
    for did, gs in gruppi.items():
        esistenti = gruppi_coppia(db, scuola_id, did)
        in_gruppo = {c: set(g) for g in esistenti for c in g}
        for g in gs:
            mancanti = [c for c in g if c not in in_gruppo]
            if mancanti:
                for a, b in itertools.combinations(sorted(g), 2):
                    nuovi_accoppiamenti.append((did, a, b))
            for c in g:
                if c in in_gruppo and in_gruppo[c] != set(g):
                    divergenze.append((did, c, set(g), in_gruppo[c]))

    nome_doc = {d.id: d.nome for d in docenti}
    esistenti_asg = {(a.docente_id, a.classe_id, a.materia_id): a
                     for a in db.query(Assegnazione).filter_by(scuola_id=scuola_id)}
    monti = {(m.docente_id, m.classe_id, m.materia_id): m
             for m in db.query(MonteOreAnnuale).filter_by(scuola_id=scuola_id)}

    creare, cambiare, uguali = [], [], 0
    for chiave, n in sorted(ore.items(), key=lambda kv: (nome_doc[kv[0][0]], nome_classe[kv[0][1]], kv[0][2])):
        did, cid, tipo = chiave
        if chiave not in esistenti_asg:
            creare.append((chiave, n))
        m = monti.get(chiave)
        if m is None or m.ore_totali != n:
            cambiare.append((chiave, m.ore_totali if m else None, n, m.ore_erogate if m else 0))
        else:
            uguali += 1
    extra = [k for k in esistenti_asg if k not in ore]

    etichetta = lambda t: "In coppia" if t == coppia_id else "Singola"  # noqa: E731
    print(f"Righe Excel -> {len(ore)} assegnazioni (docente+classe+tipo); già con ore giuste: {uguali}")
    print(f"\n== Accoppiamenti da creare: {len(nuovi_accoppiamenti)}")
    for did, a, b in nuovi_accoppiamenti:
        print(f"  {nome_doc[did]}: {nome_classe[a]} + {nome_classe[b]}")
    print(f"\n== Assegnazioni mancanti da creare: {len(creare)}")
    for (did, cid, tipo), n in creare:
        print(f"  {nome_doc[did]} | {nome_classe[cid]} | {etichetta(tipo)} | {n}h")
    print(f"\n== Ore da cambiare: {len(cambiare)}")
    for (did, cid, tipo), vecchie, n, erogate in cambiare:
        avviso = "  !! < ore erogate" if n < erogate else ""
        print(f"  {nome_doc[did]} | {nome_classe[cid]} | {etichetta(tipo)} | {vecchie} -> {n} (erogate {erogate}){avviso}")
    print(f"\n== Nel DB ma non nell'Excel (NON toccate): {len(extra)}")
    for did, cid, tipo in sorted(extra, key=lambda k: (nome_doc[k[0]], nome_classe[k[1]])):
        m = monti.get((did, cid, tipo))
        print(f"  {nome_doc[did]} | {nome_classe[cid]} | {etichetta(tipo)} | {m.ore_totali if m else '-'}h")
    print(f"\n== Gruppi in coppia diversi da quelli del DB (lasciati com'erano): {len(divergenze)}")
    for did, cid, nuovo, vecchio in divergenze:
        print(f"  {nome_doc[did]} | {nome_classe[cid]}: Excel {sorted(nome_classe[c] for c in nuovo)} "
              f"vs DB {sorted(nome_classe[c] for c in vecchio)}")
    for p in problemi:
        print(p)

    if not applica:
        print("\nSimulazione: nulla scritto. Aggiungi --applica per scrivere.")
        db.rollback()
        return

    for did, a, b in nuovi_accoppiamenti:
        db.add(ClasseAccoppiata(scuola_id=scuola_id, classe_a_id=a, classe_b_id=b, materia_id=coppia_id,
                                docente_id=did, note=NOTE))
    for (did, cid, tipo), n in ore.items():
        trio = dict(scuola_id=scuola_id, docente_id=did, classe_id=cid, materia_id=tipo)
        if (did, cid, tipo) not in esistenti_asg:
            db.add(Assegnazione(singola=tipo == singola_id, **trio))
        m = monti.get((did, cid, tipo))
        if m:
            m.ore_totali = n
        else:
            db.add(MonteOreAnnuale(**trio, ore_totali=n, ore_erogate=0))
    db.commit()
    print("\nScritto sul DB.")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        sys.exit(__doc__)
    main(args[0], "--applica" in sys.argv)
