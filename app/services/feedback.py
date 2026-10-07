"""Admin ratings of generated schedules (collection only, see OrarioFeedback)."""
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models import AuditLog, OrarioFeedback, OrarioSettimanale

# Reasons the admin can pick, keyed by a stable code. Each one corresponds to
# a soft constraint of the solver (app/domain/solver.py), so a low rating with
# a reason can later be turned into a weight adjustment for that constraint.
MOTIVI: Dict[str, str] = {
    "classe_late_start": "Classi che iniziano tardi",
    "friday_late_start": "Venerdì non inizia alle 8",
    "teoria_consecutive": "Troppe ore di teoria consecutive",
    "paired_consecutive": "Stesso docente su ore consecutive della stessa coppia",
    "paired_hours": "Più ore in coppia nello stesso giorno per un docente",
    "pratica_block": "Blocchi di pratica spezzati o troppo corti",
    "contractor_gap": "Buchi (ore libere) nei docenti a contratto",
    "single_classe_day": "Docente tutto il giorno sulla stessa classe",
    "ore_target_deviation": "Ore settimanali lontane dal target",
    "classe_unfilled": "Ore scoperte nelle classi",
    "altro": "Altro (vedi nota)",
}


class UnknownMotivo(ValueError):
    pass


class FeedbackService:
    def __init__(self, db: Session):
        self.db = db

    def _orario(self, scuola_id: str, week_start: date) -> Optional[OrarioSettimanale]:
        return self.db.query(OrarioSettimanale).filter(
            OrarioSettimanale.scuola_id == scuola_id,
            OrarioSettimanale.settimana_inizio == week_start,
        ).first()

    @staticmethod
    def _to_dict(f: OrarioFeedback) -> Dict[str, Any]:
        return {
            "id": f.id,
            "voto": f.voto,
            "motivi": f.motivi or [],
            "nota": f.nota,
            "quality_score": f.quality_score,
            "quality_level": f.quality_level,
            "n_conflitti_soft": f.n_conflitti_soft,
            "stato": f.stato,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }

    def get(self, scuola_id: str, week_start: date) -> Optional[Dict[str, Any]]:
        """Ratings of the week, newest first, plus the available reasons.
        None if the week has no schedule."""
        orario = self._orario(scuola_id, week_start)
        if not orario:
            return None
        rows = (
            self.db.query(OrarioFeedback)
            .filter(OrarioFeedback.orario_settimanale_id == orario.id)
            .order_by(OrarioFeedback.created_at.desc(), OrarioFeedback.id)
            .all()
        )
        history = [self._to_dict(f) for f in rows]
        return {
            "motivi_disponibili": [{"code": c, "label": l} for c, l in MOTIVI.items()],
            "current": history[0] if history else None,
            "history": history,
            "schedule": {
                "quality_score": orario.quality_score,
                "quality_level": orario.quality_level,
                "stato": orario.stato,
            },
        }

    def add(
        self,
        scuola_id: str,
        week_start: date,
        voto: int,
        motivi: List[str],
        nota: Optional[str],
        admin_id: Optional[str],
    ) -> Optional[Dict[str, Any]]:
        orario = self._orario(scuola_id, week_start)
        if not orario:
            return None
        unknown = [m for m in motivi if m not in MOTIVI]
        if unknown:
            raise UnknownMotivo(f"Motivi sconosciuti: {', '.join(unknown)}")

        nota = (nota or "").strip() or None
        fb = OrarioFeedback(
            orario_settimanale_id=orario.id,
            admin_id=admin_id,
            voto=voto,
            motivi=list(dict.fromkeys(motivi)),  # dedupe, keep order
            nota=nota,
            quality_score=orario.quality_score,
            quality_level=orario.quality_level,
            n_conflitti_soft=orario.n_conflitti_soft,
            stato=orario.stato,
            # set here (microsecond precision), not by the DB's now(): with
            # second-resolution timestamps two ratings in the same second
            # would tie and "newest first" would fall back to the random id.
            created_at=datetime.utcnow(),
        )
        self.db.add(fb)
        self.db.add(AuditLog(
            scuola_id=scuola_id,
            orario_settimanale_id=orario.id,
            azione="SCHEDULE_FEEDBACK",
            admin_id=admin_id,
            dettagli={"voto": voto, "motivi": fb.motivi},
        ))
        self.db.commit()
        self.db.refresh(fb)
        return self._to_dict(fb)
