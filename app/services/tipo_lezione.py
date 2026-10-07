"""
Tipo di lezione al posto della materia.

Il concetto di materia non è più usato: un docente lavora su una classe in due
modi distinti, ognuno con il proprio monte ore, le proprie ore settimanali e la
propria scalatura:

- "In coppia": lezione in comune con altre classi accoppiate (vedi Accoppiamenti);
- "Singola": il docente è con quella classe da solo.

Sotto il cofano il tipo occupa la colonna materia_id (assegnazione, monte ore,
accoppiamento, lezione), che è già parte della chiave docente+classe+materia usata
ovunque: così monte ore e lezioni di un tipo non si mescolano mai con l'altro.
"""
import logging
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import Assegnazione, ClasseAccoppiata, Materia, MonteOreAnnuale, Scuola, SlotLezione

logger = logging.getLogger(__name__)

COPPIA_NOME = "In coppia"
SINGOLA_NOME = "Singola"


def tipo_materie(db: Session, scuola_id: str) -> Tuple[str, str]:
    """(id "In coppia", id "Singola") della scuola, creati al primo uso."""
    esistenti = {m.nome: m for m in db.query(Materia).filter(Materia.scuola_id == scuola_id).all()}
    base = next((m for m in esistenti.values() if m.nome not in (COPPIA_NOME, SINGOLA_NOME)), None)
    tipo = base.tipo if base else "TEORIA"
    peso = base.peso_cognitivo if base else "MEDIO"
    ids = []
    for nome in (COPPIA_NOME, SINGOLA_NOME):
        m = esistenti.get(nome)
        if not m:
            m = Materia(scuola_id=scuola_id, nome=nome, tipo=tipo, peso_cognitivo=peso)
            db.add(m)
            db.flush()
        ids.append(m.id)
    return ids[0], ids[1]


def gruppi_coppia(db: Session, scuola_id: str, docente_id: str) -> List[List[str]]:
    """Gruppi di classi collegate dagli accoppiamenti **del docente** (anche indirettamente:
    A+B, A+C, B+C -> un gruppo A, B, C). Sono le classi con cui fa la stessa lezione in comune."""
    comps: List[set] = []
    for p in db.query(ClasseAccoppiata).filter_by(scuola_id=scuola_id, docente_id=docente_id).all():
        merged = {p.classe_a_id, p.classe_b_id}
        for c in [c for c in comps if c & merged]:
            merged |= c
            comps.remove(c)
        comps.append(merged)
    return [sorted(c) for c in comps]


def unisci_doppioni(db: Session, scuola_id: str) -> int:
    """Più assegnazioni uguali (stesso docente, classe e tipo) sono la stessa entità: ne resta una
    (la più vecchia) e i monte ore doppi si fondono al valore più alto. Un doppione rende ambigua
    la lezione salvata e rompe l'uguaglianza delle coppie. Idempotente; ritorna le righe tolte."""
    tolte = 0
    per_trio: Dict[Tuple[str, str, str], List[Assegnazione]] = {}
    for a in db.query(Assegnazione).filter_by(scuola_id=scuola_id).order_by(Assegnazione.created_at, Assegnazione.id):
        per_trio.setdefault((a.docente_id, a.classe_id, a.materia_id), []).append(a)
    for (docente_id, classe_id, materia_id), asgs in per_trio.items():
        if len(asgs) > 1:
            for extra in asgs[1:]:
                db.delete(extra)
                tolte += 1
        monti = db.query(MonteOreAnnuale).filter_by(
            scuola_id=scuola_id, docente_id=docente_id, classe_id=classe_id, materia_id=materia_id,
        ).order_by(MonteOreAnnuale.created_at, MonteOreAnnuale.id).all()
        if len(monti) > 1:
            monti[0].ore_totali = max(m.ore_totali or 0 for m in monti)
            monti[0].ore_erogate = max(m.ore_erogate or 0 for m in monti)
            for extra in monti[1:]:
                db.delete(extra)
                tolte += 1
    if tolte:
        logger.info(f"Doppioni uniti: {tolte} righe tolte")
    return tolte


def allinea_residui_coppie(db: Session, scuola_id: str) -> int:
    """Le classi di un gruppo in coppia hanno lo stesso monte ore: una lezione doppia consuma
    una sola volta il monte della coppia. Allinea ore totali e ore fatte di ogni gruppo al valore
    più alto (nessuno perde ore) e crea il monte ore mancante di una classe. Idempotente.
    Ritorna quante righe di monte ore sono state toccate."""
    coppia, _ = tipo_materie(db, scuola_id)
    toccate = 0
    docenti = {p.docente_id for p in db.query(ClasseAccoppiata).filter_by(scuola_id=scuola_id).all() if p.docente_id}
    for docente_id in docenti:
        for gruppo in gruppi_coppia(db, scuola_id, docente_id):
            asg_classi = {
                a.classe_id for a in db.query(Assegnazione).filter(
                    Assegnazione.scuola_id == scuola_id, Assegnazione.docente_id == docente_id,
                    Assegnazione.materia_id == coppia, Assegnazione.classe_id.in_(gruppo),
                ).all()
            }
            if len(asg_classi) < 2:
                continue  # niente da allineare
            righe = db.query(MonteOreAnnuale).filter(
                MonteOreAnnuale.scuola_id == scuola_id, MonteOreAnnuale.docente_id == docente_id,
                MonteOreAnnuale.materia_id == coppia, MonteOreAnnuale.classe_id.in_(asg_classi),
            ).all()
            if not righe:
                continue
            totali = max(r.ore_totali or 0 for r in righe)
            fatte = max(r.ore_erogate or 0 for r in righe)
            presenti = {r.classe_id for r in righe}
            for r in righe:
                if (r.ore_totali, r.ore_erogate) != (totali, fatte):
                    r.ore_totali, r.ore_erogate = totali, fatte
                    toccate += 1
            for classe_id in asg_classi - presenti:
                db.add(MonteOreAnnuale(
                    scuola_id=scuola_id, docente_id=docente_id, classe_id=classe_id, materia_id=coppia,
                    ore_totali=totali, ore_erogate=fatte,
                ))
                toccate += 1
    if toccate:
        logger.info(f"Residui delle coppie allineati: {toccate} righe di monte ore")
    return toccate


def normalize_tipo_lezione(db: Session, scuola_id: Optional[str] = None) -> None:
    """Porta i dati esistenti al modello docente+classe+tipo (idempotente).

    - gli accoppiamenti diventano "In coppia";
    - un'assegnazione è "In coppia" se la sua classe è in un accoppiamento del docente (o senza
      docente) e non è marcata singola, altrimenti "Singola";
    - il monte ore segue la sua assegnazione; se docente+classe hanno entrambi i tipi, il tipo
      "Singola" riceve un monte ore proprio (copia dei valori attuali, ore fatte a 0);
    - le lezioni già generate passano al tipo della loro assegnazione.
    """
    scuole = [scuola_id] if scuola_id else [s.id for s in db.query(Scuola).all()]
    for sid in scuole:
        _normalize_scuola(db, sid)
    db.commit()


def _normalize_scuola(db: Session, sid: str) -> None:
    assegnazioni = db.query(Assegnazione).filter_by(scuola_id=sid).all()
    pairings = db.query(ClasseAccoppiata).filter_by(scuola_id=sid).all()
    if not assegnazioni and not pairings:
        return
    coppia, singola = tipo_materie(db, sid)
    tipi = {coppia, singola}

    for p in pairings:
        p.materia_id = coppia

    def in_coppia(a: Assegnazione) -> bool:
        return any(
            a.classe_id in (p.classe_a_id, p.classe_b_id) and (p.docente_id in (None, a.docente_id))
            for p in pairings
        )

    daspostare = [a for a in assegnazioni if a.materia_id not in tipi]
    if daspostare:
        monte_per_trio: Dict[Tuple[str, str, str], List[MonteOreAnnuale]] = {}
        for m in db.query(MonteOreAnnuale).filter_by(scuola_id=sid).order_by(MonteOreAnnuale.created_at).all():
            monte_per_trio.setdefault((m.docente_id, m.classe_id, m.materia_id), []).append(m)

        bersaglio = {a.id: (singola if (a.singola or not in_coppia(a)) else coppia) for a in daspostare}
        per_trio: Dict[Tuple[str, str, str], List[Assegnazione]] = {}
        for a in daspostare:
            per_trio.setdefault((a.docente_id, a.classe_id, a.materia_id), []).append(a)

        for trio, asgs in per_trio.items():
            target = {bersaglio[a.id] for a in asgs}
            monti = monte_per_trio.get(trio, [])
            if target == {coppia}:
                for m in monti:
                    m.materia_id = coppia
            elif target == {singola}:
                for m in monti:
                    m.materia_id = singola
            else:  # entrambi i tipi: il monte esistente resta alla coppia, la singola ne ha uno suo
                for i, m in enumerate(monti):
                    m.materia_id = coppia if i == 0 else singola
                if len(monti) < 2 and monti:
                    db.add(MonteOreAnnuale(
                        scuola_id=sid, docente_id=trio[0], classe_id=trio[1], materia_id=singola,
                        ore_totali=monti[0].ore_totali, ore_erogate=0,
                    ))
        for a in daspostare:
            a.materia_id = bersaglio[a.id]
            a.singola = a.materia_id == singola
        db.flush()

    # Lezioni già generate: al tipo dell'assegnazione corrispondente.
    tipi_per_coppia: Dict[Tuple[str, str], set] = {}
    for a in db.query(Assegnazione).filter_by(scuola_id=sid).all():
        tipi_per_coppia.setdefault((a.docente_id, a.classe_id), set()).add(a.materia_id)
    for s in db.query(SlotLezione).all():
        if s.materia_id in tipi:
            continue
        disponibili = tipi_per_coppia.get((s.docente_id, s.classe_id), set()) & tipi
        voluto = coppia if s.accoppiata else singola
        s.materia_id = voluto if (voluto in disponibili or not disponibili) else next(iter(disponibili))

    db.flush()
    unisci_doppioni(db, sid)
    db.flush()
    allinea_residui_coppie(db, sid)
