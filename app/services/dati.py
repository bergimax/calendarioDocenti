"""
Business logic for the "Dati scuola" post-setup management page
(frontend/src/routes/dati.*.tsx via CrudTable): CRUD for classi, materie,
assegnazioni (+ their monte ore), accoppiamenti and calendario. Docenti CRUD
lives in AvailabilityService instead, since GET /api/teachers was already
there for the Disponibilità page.

Every CrudTable form posts every field as a string (HTML form values), and
on edit resends every column of the row being edited (including the id
field itself) - so each *_from_form helper below tolerates missing/extra
keys and coerces types rather than assuming a strict shape.
"""

from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from datetime import date
from typing import Any, Dict, List, Optional
from app.models import Classe, Materia, Assegnazione, MonteOreAnnuale, ClasseAccoppiata, CalendarioAnnuale
import logging

logger = logging.getLogger(__name__)


def _int_or(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    return int(value)


def _bool_from_form(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes", "on")


class SchoolDataService:
    """CRUD for the "Dati scuola" entities other than docenti."""

    def __init__(self, db: Session):
        self.db = db

    # ===== Classi =====

    def list_classi(self, scuola_id: str) -> List[Dict[str, Any]]:
        rows = self.db.query(Classe).filter_by(scuola_id=scuola_id).order_by(Classe.nome).all()
        return [self._classe_dict(c) for c in rows]

    def create_classe(self, scuola_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        nome = (data.get("nome") or "").strip()
        if not nome:
            raise ValueError("nome is required")
        classe = Classe(
            scuola_id=scuola_id,
            nome=nome,
            n_studenti=_int_or(data.get("n_studenti"), 0),
            gruppo=(data.get("gruppo") or "").strip() or None,
        )
        self.db.add(classe)
        self.db.commit()
        return self._classe_dict(classe)

    def update_classe(self, scuola_id: str, classe_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        classe = self.db.query(Classe).filter_by(id=classe_id, scuola_id=scuola_id).first()
        if not classe:
            raise ValueError(f"Classe {classe_id!r} not found")
        if data.get("nome"):
            classe.nome = data["nome"].strip()
        if "n_studenti" in data:
            classe.n_studenti = _int_or(data.get("n_studenti"), classe.n_studenti)
        if "gruppo" in data:
            classe.gruppo = (data.get("gruppo") or "").strip() or None
        self.db.commit()
        return self._classe_dict(classe)

    def delete_classe(self, scuola_id: str, classe_id: str) -> None:
        classe = self.db.query(Classe).filter_by(id=classe_id, scuola_id=scuola_id).first()
        if not classe:
            raise ValueError(f"Classe {classe_id!r} not found")
        try:
            self.db.delete(classe)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ValueError("Cannot delete: this classe has related assignments, pairings, or schedule slots")

    @staticmethod
    def _classe_dict(c: Classe) -> Dict[str, Any]:
        return {"classe_id": c.id, "nome": c.nome, "n_studenti": c.n_studenti, "gruppo": c.gruppo}

    # ===== Materie =====

    def list_materie(self, scuola_id: str) -> List[Dict[str, Any]]:
        rows = self.db.query(Materia).filter_by(scuola_id=scuola_id).order_by(Materia.nome).all()
        return [self._materia_dict(m) for m in rows]

    def create_materia(self, scuola_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        nome = (data.get("nome") or "").strip()
        if not nome:
            raise ValueError("nome is required")
        tipo = (data.get("tipo") or "TEORIA").strip().upper()
        if tipo not in ("TEORIA", "PRATICA"):
            raise ValueError(f"tipo must be TEORIA or PRATICA, got {tipo!r}")
        peso = (data.get("peso_cognitivo") or "MEDIO").strip().upper()
        if peso not in ("ALTO", "MEDIO", "BASSO"):
            raise ValueError(f"peso_cognitivo must be ALTO/MEDIO/BASSO, got {peso!r}")

        materia = Materia(scuola_id=scuola_id, nome=nome, tipo=tipo, peso_cognitivo=peso)
        self.db.add(materia)
        self.db.commit()
        return self._materia_dict(materia)

    def update_materia(self, scuola_id: str, materia_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        materia = self.db.query(Materia).filter_by(id=materia_id, scuola_id=scuola_id).first()
        if not materia:
            raise ValueError(f"Materia {materia_id!r} not found")
        if data.get("nome"):
            materia.nome = data["nome"].strip()
        if data.get("tipo"):
            tipo = data["tipo"].strip().upper()
            if tipo not in ("TEORIA", "PRATICA"):
                raise ValueError(f"tipo must be TEORIA or PRATICA, got {tipo!r}")
            materia.tipo = tipo
        if data.get("peso_cognitivo"):
            peso = data["peso_cognitivo"].strip().upper()
            if peso not in ("ALTO", "MEDIO", "BASSO"):
                raise ValueError(f"peso_cognitivo must be ALTO/MEDIO/BASSO, got {peso!r}")
            materia.peso_cognitivo = peso
        self.db.commit()
        return self._materia_dict(materia)

    def delete_materia(self, scuola_id: str, materia_id: str) -> None:
        materia = self.db.query(Materia).filter_by(id=materia_id, scuola_id=scuola_id).first()
        if not materia:
            raise ValueError(f"Materia {materia_id!r} not found")
        try:
            self.db.delete(materia)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ValueError("Cannot delete: this materia has related assignments, pairings, or schedule slots")

    @staticmethod
    def _materia_dict(m: Materia) -> Dict[str, Any]:
        return {"materia_id": m.id, "nome": m.nome, "tipo": m.tipo, "peso_cognitivo": m.peso_cognitivo}

    def _default_materia_id(self, scuola_id: str) -> str:
        """Fallback materia for assegnazioni/accoppiamenti created without one
        picked in the UI (the "Dati scuola" forms no longer ask for materia -
        it isn't meaningful for accoppiamenti, which are compresenza detected
        from the calendar, not a shared subject - see
        scripts/rederive_monte_ore_and_pairings.py)."""
        materia = self.db.query(Materia).filter_by(scuola_id=scuola_id).first()
        if not materia:
            raise ValueError("No materia exists for this scuola - create one first")
        return materia.id

    # ===== Assegnazioni (+ monte ore) =====
    # The "Dati scuola" page's single form conflates two tables: the
    # docente<->classe<->materia link (Assegnazione) and its annual hours
    # budget (MonteOreAnnuale) - CrudTable's one row = one assignment_id
    # covers both, matching the page title "Assegnazioni e monte ore".

    def list_assegnazioni(self, scuola_id: str) -> List[Dict[str, Any]]:
        rows = self.db.query(Assegnazione).filter_by(scuola_id=scuola_id).all()
        return [self._assegnazione_dict(a) for a in rows]

    def _partner(self, a: Assegnazione) -> tuple[Optional[str], Optional[str]]:
        """(classe_id, assignment_id) della classe con cui `a` è accoppiata, se c'è.

        Accoppiata = esiste un accoppiamento con la stessa materia che include la
        classe ed è del docente (o senza docente specifico). L'assignment_id è
        None se l'altra classe non è (ancora) assegnata allo stesso docente.
        """
        if a.singola:
            return None, None
        pairing = self.db.query(ClasseAccoppiata).filter(
            ClasseAccoppiata.scuola_id == a.scuola_id,
            ClasseAccoppiata.materia_id == a.materia_id,
            (ClasseAccoppiata.classe_a_id == a.classe_id) | (ClasseAccoppiata.classe_b_id == a.classe_id),
            (ClasseAccoppiata.docente_id.is_(None)) | (ClasseAccoppiata.docente_id == a.docente_id),
        ).first()
        if not pairing:
            return None, None
        other = pairing.classe_b_id if pairing.classe_a_id == a.classe_id else pairing.classe_a_id
        partner = self.db.query(Assegnazione).filter_by(
            scuola_id=a.scuola_id, docente_id=a.docente_id, classe_id=other, materia_id=a.materia_id,
            singola=False,
        ).first()
        return other, partner.id if partner else None

    def _monte(self, a: Assegnazione) -> Optional[MonteOreAnnuale]:
        return self.db.query(MonteOreAnnuale).filter_by(
            scuola_id=a.scuola_id, docente_id=a.docente_id, classe_id=a.classe_id, materia_id=a.materia_id,
        ).first()

    def create_assegnazione(self, scuola_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        docente_id = (data.get("docente_id") or "").strip()
        accoppiamento_id = (data.get("accoppiamento_id") or "").strip()
        materia_id = (data.get("materia_id") or "").strip() or self._default_materia_id(scuola_id)

        # Un accoppiamento definito in "Accoppiamenti" genera un'assegnazione
        # per ciascuna delle due classi, con lo stesso monte ore.
        if accoppiamento_id:
            pairing = self.db.query(ClasseAccoppiata).filter_by(id=accoppiamento_id, scuola_id=scuola_id).first()
            if not pairing:
                raise ValueError(f"Accoppiamento {accoppiamento_id!r} not found")
            classe_ids = [pairing.classe_a_id, pairing.classe_b_id]
            materia_id = pairing.materia_id or materia_id
        else:
            classe_ids = [(data.get("classe_id") or "").strip()]

        if not (docente_id and all(classe_ids) and materia_id):
            raise ValueError("docente_id and classe_id are required")

        created = []
        for classe_id in classe_ids:
            trio = dict(scuola_id=scuola_id, docente_id=docente_id, classe_id=classe_id, materia_id=materia_id)
            if accoppiamento_id and self.db.query(Assegnazione).filter_by(singola=False, **trio).first():
                continue  # già assegnata: non duplicare
            # Una classe scelta da sola resta singola anche se fa parte di un accoppiamento.
            asg = Assegnazione(singola=not accoppiamento_id, **trio)
            # Il monte ore è per (docente, classe, materia): se c'è già, si aggiorna.
            monte = self.db.query(MonteOreAnnuale).filter_by(**trio).first()
            if not monte:
                monte = MonteOreAnnuale(**trio, ore_totali=0, ore_erogate=0)
                self.db.add(monte)
            if data.get("ore_totali") not in (None, ""):
                monte.ore_totali = _int_or(data.get("ore_totali"), monte.ore_totali)
            if data.get("ore_erogate") not in (None, ""):
                monte.ore_erogate = _int_or(data.get("ore_erogate"), monte.ore_erogate)
            self.db.add(asg)
            created.append(asg)
        if not created:
            raise ValueError("Questo accoppiamento è già assegnato al docente")
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ValueError("docente_id, classe_id or materia_id does not reference an existing record")
        return self._assegnazione_dict(created[0])

    def update_assegnazione(self, scuola_id: str, assignment_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        asg = self.db.query(Assegnazione).filter_by(id=assignment_id, scuola_id=scuola_id).first()
        if not asg:
            raise ValueError(f"Assegnazione {assignment_id!r} not found")

        # The monte_ore row is matched by the *current* (docente,classe,materia)
        # trio before any of them change below.
        monte = self.db.query(MonteOreAnnuale).filter_by(
            scuola_id=scuola_id, docente_id=asg.docente_id, classe_id=asg.classe_id, materia_id=asg.materia_id,
        ).first()
        # La riga di un'assegnazione accoppiata rappresenta entrambe le classi:
        # ore e docente si applicano anche all'altra.
        _, partner_id = self._partner(asg)
        partner = self.db.query(Assegnazione).filter_by(id=partner_id).first() if partner_id else None
        partner_monte = self._monte(partner) if partner else None

        if data.get("docente_id"):
            asg.docente_id = data["docente_id"].strip()
        if data.get("classe_id"):
            asg.classe_id = data["classe_id"].strip()
        if data.get("materia_id"):
            asg.materia_id = data["materia_id"].strip()

        if not monte:
            monte = MonteOreAnnuale(
                scuola_id=scuola_id, docente_id=asg.docente_id, classe_id=asg.classe_id, materia_id=asg.materia_id,
                ore_totali=0, ore_erogate=0,
            )
            self.db.add(monte)
        else:
            monte.docente_id = asg.docente_id
            monte.classe_id = asg.classe_id
            monte.materia_id = asg.materia_id

        if "ore_totali" in data:
            monte.ore_totali = _int_or(data.get("ore_totali"), monte.ore_totali)
        if "ore_erogate" in data:
            monte.ore_erogate = _int_or(data.get("ore_erogate"), monte.ore_erogate)

        if partner:
            if data.get("docente_id"):
                partner.docente_id = asg.docente_id
            if partner_monte:
                partner_monte.docente_id = partner.docente_id
                partner_monte.ore_totali = monte.ore_totali
                partner_monte.ore_erogate = monte.ore_erogate

        self.db.commit()
        return self._assegnazione_dict(asg)

    def delete_assegnazione(self, scuola_id: str, assignment_id: str) -> None:
        asg = self.db.query(Assegnazione).filter_by(id=assignment_id, scuola_id=scuola_id).first()
        if not asg:
            raise ValueError(f"Assegnazione {assignment_id!r} not found")
        # La riga di un'assegnazione accoppiata rappresenta entrambe le classi.
        _, partner_id = self._partner(asg)
        targets = [asg]
        if partner_id:
            targets.append(self.db.query(Assegnazione).filter_by(id=partner_id).first())
        try:
            for t in targets:
                trio = dict(scuola_id=scuola_id, docente_id=t.docente_id, classe_id=t.classe_id, materia_id=t.materia_id)
                shared = self.db.query(Assegnazione).filter(
                    Assegnazione.id != t.id,
                    *[getattr(Assegnazione, k) == v for k, v in trio.items()],
                ).count()
                if not shared:
                    self.db.query(MonteOreAnnuale).filter_by(**trio).delete(synchronize_session=False)
                self.db.delete(t)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ValueError("Cannot delete: this assignment has related schedule slots")

    def _assegnazione_dict(self, a: Assegnazione) -> Dict[str, Any]:
        monte = self.db.query(MonteOreAnnuale).filter_by(
            scuola_id=a.scuola_id, docente_id=a.docente_id, classe_id=a.classe_id, materia_id=a.materia_id,
        ).first()
        partner_classe_id, partner_assignment_id = self._partner(a)
        return {
            "assignment_id": a.id,
            "docente_id": a.docente_id,
            "classe_id": a.classe_id,
            "materia_id": a.materia_id,
            "ore_totali": monte.ore_totali if monte else 0,
            "ore_erogate": monte.ore_erogate if monte else 0,
            "singola": bool(a.singola),
            "partner_classe_id": partner_classe_id,
            "partner_assignment_id": partner_assignment_id,
        }

    # ===== Accoppiamenti =====

    def list_accoppiamenti(self, scuola_id: str) -> List[Dict[str, Any]]:
        rows = self.db.query(ClasseAccoppiata).filter_by(scuola_id=scuola_id).all()
        return [self._accoppiamento_dict(c) for c in rows]

    def create_accoppiamento(self, scuola_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        classe_a_id = (data.get("classe_a_id") or "").strip()
        classe_b_id = (data.get("classe_b_id") or "").strip()
        materia_id = (data.get("materia_id") or "").strip() or self._default_materia_id(scuola_id)
        if not (classe_a_id and classe_b_id and materia_id):
            raise ValueError("classe_a_id and classe_b_id are required")

        pairing = ClasseAccoppiata(
            scuola_id=scuola_id, classe_a_id=classe_a_id, classe_b_id=classe_b_id, materia_id=materia_id,
            docente_id=(data.get("docente_id") or "").strip() or None,
            note=(data.get("note") or "").strip() or None,
        )
        self.db.add(pairing)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ValueError("classe_a_id, classe_b_id or materia_id does not reference an existing record")
        return self._accoppiamento_dict(pairing)

    def update_accoppiamento(self, scuola_id: str, pairing_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        pairing = self.db.query(ClasseAccoppiata).filter_by(id=pairing_id, scuola_id=scuola_id).first()
        if not pairing:
            raise ValueError(f"Accoppiamento {pairing_id!r} not found")
        if data.get("classe_a_id"):
            pairing.classe_a_id = data["classe_a_id"].strip()
        if data.get("classe_b_id"):
            pairing.classe_b_id = data["classe_b_id"].strip()
        if data.get("materia_id"):
            pairing.materia_id = data["materia_id"].strip()
        if "docente_id" in data:
            pairing.docente_id = (data.get("docente_id") or "").strip() or None
        if "note" in data:
            pairing.note = (data.get("note") or "").strip() or None
        self.db.commit()
        return self._accoppiamento_dict(pairing)

    def delete_accoppiamento(self, scuola_id: str, pairing_id: str) -> None:
        pairing = self.db.query(ClasseAccoppiata).filter_by(id=pairing_id, scuola_id=scuola_id).first()
        if not pairing:
            raise ValueError(f"Accoppiamento {pairing_id!r} not found")
        self.db.delete(pairing)
        self.db.commit()

    @staticmethod
    def _accoppiamento_dict(c: ClasseAccoppiata) -> Dict[str, Any]:
        return {
            "pairing_id": c.id,
            "classe_a_id": c.classe_a_id,
            "classe_b_id": c.classe_b_id,
            "materia_id": c.materia_id,
            "docente_id": c.docente_id,
            "note": c.note,
        }

    # ===== Calendario =====

    def list_calendario(self, scuola_id: str) -> List[Dict[str, Any]]:
        rows = self.db.query(CalendarioAnnuale).filter_by(scuola_id=scuola_id).order_by(CalendarioAnnuale.data).all()
        return [self._calendario_dict(c) for c in rows]

    def create_calendario(self, scuola_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        data_str = (data.get("data") or "").strip()
        if not data_str:
            raise ValueError("data is required")
        try:
            data_val = date.fromisoformat(data_str)
        except ValueError:
            raise ValueError(f"Invalid data: {data_str!r} (expected YYYY-MM-DD)")

        entry = CalendarioAnnuale(
            scuola_id=scuola_id,
            data=data_val,
            gruppo=(data.get("gruppo") or "").strip() or None,
            ore_max_giornata=_int_or(data.get("ore_max_giornata"), 6),
            ora_inizio_min=_int_or(data.get("ora_inizio_min"), None),
            flag_chiusura=_bool_from_form(data.get("flag_chiusura")),
            flag_stage_classe_id=(data.get("flag_stage_classe_id") or "").strip() or None,
            flag_stage_gruppo=_bool_from_form(data.get("flag_stage_gruppo")),
        )
        self.db.add(entry)
        self.db.commit()
        return self._calendario_dict(entry)

    def update_calendario(self, scuola_id: str, date_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        entry = self.db.query(CalendarioAnnuale).filter_by(id=date_id, scuola_id=scuola_id).first()
        if not entry:
            raise ValueError(f"Calendario entry {date_id!r} not found")
        if data.get("data"):
            try:
                entry.data = date.fromisoformat(data["data"].strip())
            except ValueError:
                raise ValueError(f"Invalid data: {data['data']!r} (expected YYYY-MM-DD)")
        if "gruppo" in data:
            entry.gruppo = (data.get("gruppo") or "").strip() or None
        if "ore_max_giornata" in data:
            entry.ore_max_giornata = _int_or(data.get("ore_max_giornata"), entry.ore_max_giornata)
        if "ora_inizio_min" in data:
            entry.ora_inizio_min = _int_or(data.get("ora_inizio_min"), None)
        if "flag_chiusura" in data:
            entry.flag_chiusura = _bool_from_form(data.get("flag_chiusura"))
        if "flag_stage_classe_id" in data:
            entry.flag_stage_classe_id = (data.get("flag_stage_classe_id") or "").strip() or None
        if "flag_stage_gruppo" in data:
            entry.flag_stage_gruppo = _bool_from_form(data.get("flag_stage_gruppo"))
        self.db.commit()
        return self._calendario_dict(entry)

    def delete_calendario(self, scuola_id: str, date_id: str) -> None:
        entry = self.db.query(CalendarioAnnuale).filter_by(id=date_id, scuola_id=scuola_id).first()
        if not entry:
            raise ValueError(f"Calendario entry {date_id!r} not found")
        self.db.delete(entry)
        self.db.commit()

    @staticmethod
    def _calendario_dict(c: CalendarioAnnuale) -> Dict[str, Any]:
        return {
            "date_id": c.id,
            "data": c.data.isoformat(),
            "gruppo": c.gruppo,
            "ore_max_giornata": c.ore_max_giornata,
            "ora_inizio_min": c.ora_inizio_min,
            "flag_chiusura": c.flag_chiusura,
            "flag_stage_classe_id": c.flag_stage_classe_id,
            "flag_stage_gruppo": c.flag_stage_gruppo,
        }
