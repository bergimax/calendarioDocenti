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

    # ===== Assegnazioni (+ monte ore) =====
    # The "Dati scuola" page's single form conflates two tables: the
    # docente<->classe<->materia link (Assegnazione) and its annual hours
    # budget (MonteOreAnnuale) - CrudTable's one row = one assignment_id
    # covers both, matching the page title "Assegnazioni e monte ore".

    def list_assegnazioni(self, scuola_id: str) -> List[Dict[str, Any]]:
        rows = self.db.query(Assegnazione).filter_by(scuola_id=scuola_id).all()
        return [self._assegnazione_dict(a) for a in rows]

    def create_assegnazione(self, scuola_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        docente_id = (data.get("docente_id") or "").strip()
        classe_id = (data.get("classe_id") or "").strip()
        materia_id = (data.get("materia_id") or "").strip()
        if not (docente_id and classe_id and materia_id):
            raise ValueError("docente_id, classe_id and materia_id are all required")

        asg = Assegnazione(
            scuola_id=scuola_id, docente_id=docente_id, classe_id=classe_id, materia_id=materia_id,
        )
        self.db.add(asg)
        self.db.flush()

        monte = MonteOreAnnuale(
            scuola_id=scuola_id, docente_id=docente_id, classe_id=classe_id, materia_id=materia_id,
            ore_totali=_int_or(data.get("ore_totali"), 0),
            ore_erogate=_int_or(data.get("ore_erogate"), 0),
        )
        self.db.add(monte)
        self.db.commit()
        return self._assegnazione_dict(asg)

    def update_assegnazione(self, scuola_id: str, assignment_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        asg = self.db.query(Assegnazione).filter_by(id=assignment_id, scuola_id=scuola_id).first()
        if not asg:
            raise ValueError(f"Assegnazione {assignment_id!r} not found")

        # The monte_ore row is matched by the *current* (docente,classe,materia)
        # trio before any of them change below.
        monte = self.db.query(MonteOreAnnuale).filter_by(
            scuola_id=scuola_id, docente_id=asg.docente_id, classe_id=asg.classe_id, materia_id=asg.materia_id,
        ).first()

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

        self.db.commit()
        return self._assegnazione_dict(asg)

    def delete_assegnazione(self, scuola_id: str, assignment_id: str) -> None:
        asg = self.db.query(Assegnazione).filter_by(id=assignment_id, scuola_id=scuola_id).first()
        if not asg:
            raise ValueError(f"Assegnazione {assignment_id!r} not found")
        try:
            self.db.query(MonteOreAnnuale).filter_by(
                scuola_id=scuola_id, docente_id=asg.docente_id, classe_id=asg.classe_id, materia_id=asg.materia_id,
            ).delete(synchronize_session=False)
            self.db.delete(asg)
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise ValueError("Cannot delete: this assignment has related schedule slots")

    def _assegnazione_dict(self, a: Assegnazione) -> Dict[str, Any]:
        monte = self.db.query(MonteOreAnnuale).filter_by(
            scuola_id=a.scuola_id, docente_id=a.docente_id, classe_id=a.classe_id, materia_id=a.materia_id,
        ).first()
        return {
            "assignment_id": a.id,
            "docente_id": a.docente_id,
            "classe_id": a.classe_id,
            "materia_id": a.materia_id,
            "ore_totali": monte.ore_totali if monte else 0,
            "ore_erogate": monte.ore_erogate if monte else 0,
        }

    # ===== Accoppiamenti =====

    def list_accoppiamenti(self, scuola_id: str) -> List[Dict[str, Any]]:
        rows = self.db.query(ClasseAccoppiata).filter_by(scuola_id=scuola_id).all()
        return [self._accoppiamento_dict(c) for c in rows]

    def create_accoppiamento(self, scuola_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        classe_a_id = (data.get("classe_a_id") or "").strip()
        classe_b_id = (data.get("classe_b_id") or "").strip()
        materia_id = (data.get("materia_id") or "").strip()
        if not (classe_a_id and classe_b_id and materia_id):
            raise ValueError("classe_a_id, classe_b_id and materia_id are all required")

        pairing = ClasseAccoppiata(
            scuola_id=scuola_id, classe_a_id=classe_a_id, classe_b_id=classe_b_id, materia_id=materia_id,
            note=(data.get("note") or "").strip() or None,
        )
        self.db.add(pairing)
        self.db.commit()
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
            flag_chiusura=_bool_from_form(data.get("flag_chiusura")),
            flag_stage_classe_id=(data.get("flag_stage_classe_id") or "").strip() or None,
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
        if "flag_chiusura" in data:
            entry.flag_chiusura = _bool_from_form(data.get("flag_chiusura"))
        if "flag_stage_classe_id" in data:
            entry.flag_stage_classe_id = (data.get("flag_stage_classe_id") or "").strip() or None
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
            "flag_chiusura": c.flag_chiusura,
            "flag_stage_classe_id": c.flag_stage_classe_id,
        }
