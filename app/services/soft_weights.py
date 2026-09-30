"""
Learning from the admin's schedule ratings (OrarioFeedback): turns low
ratings that name a reason into *proposals* to raise the weight of the
matching soft constraint, which the admin approves (nothing changes by
itself). See app/domain/soft_weights.py for what is tunable and why.

Deliberately conservative, since a wrong weight silently degrades every
future schedule:
- only raises weights (lowering is the admin's "reset");
- one step is at most +50% of the current weight, and never above MAX_SOFT_WEIGHT;
- needs MIN_FEEDBACK low ratings (<= 3 stars) on the same reason;
- each rating counts once: after a kind is adjusted or reset, only ratings
  given later are considered for it.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.domain.soft_weights import (
    DEFAULT_SOFT_WEIGHTS,
    MAX_SOFT_WEIGHT,
    MOTIVO_CONSTRAINTS,
    resolve_soft_weights,
)
from app.models import AuditLog, OrarioFeedback, SoftWeightAdjustment
from app.services.feedback import MOTIVI

MIN_FEEDBACK = 2       # low ratings on a reason before proposing anything
LOW_VOTE_MAX = 3       # ratings up to this many stars count as complaints
STEP_PER_POINT = 0.10  # +10% per severity point (1 star = 3, 2 = 2, 3 = 1)
MAX_STEP = 0.50        # never more than +50% in one adjustment


class UnknownKind(ValueError):
    pass


def _label(kind: str) -> str:
    """The admin-facing name of a tunable constraint (its reason's label)."""
    for code, m in MOTIVO_CONSTRAINTS.items():
        if m.tunable == kind:
            return MOTIVI[code]
    return kind


class SoftWeightService:
    def __init__(self, db: Session):
        self.db = db

    # -- current configuration ------------------------------------------------

    def _latest_by_kind(self) -> Dict[str, SoftWeightAdjustment]:
        rows = (
            self.db.query(SoftWeightAdjustment)
            .order_by(SoftWeightAdjustment.created_at.desc())
            .all()
        )
        latest: Dict[str, SoftWeightAdjustment] = {}
        for r in rows:
            latest.setdefault(r.kind, r)
        return latest

    def active_weights(self) -> Dict[str, int]:
        """Weights the solver should use: defaults + every applied adjustment."""
        overrides = {k: r.new_weight for k, r in self._latest_by_kind().items()}
        return resolve_soft_weights(overrides)

    # -- proposals ------------------------------------------------------------

    def propose(self) -> List[Dict[str, Any]]:
        weights = self.active_weights()
        latest = self._latest_by_kind()
        feedback = (
            self.db.query(OrarioFeedback)
            .filter(OrarioFeedback.voto <= LOW_VOTE_MAX)
            .order_by(OrarioFeedback.created_at)
            .all()
        )

        proposals = []
        for code, m in MOTIVO_CONSTRAINTS.items():
            kind = m.tunable
            if not kind:
                continue
            since = latest[kind].created_at if kind in latest else None
            evidence = [
                f for f in feedback
                if code in (f.motivi or []) and (since is None or (f.created_at and f.created_at > since))
            ]
            if len(evidence) < MIN_FEEDBACK:
                continue
            severity = sum(LOW_VOTE_MAX + 1 - f.voto for f in evidence)
            current = weights[kind]
            step = min(MAX_STEP, STEP_PER_POINT * severity)
            proposed = min(MAX_SOFT_WEIGHT, max(current + 1, round(current * (1 + step))))
            if proposed <= current:
                continue  # already at the cap
            proposals.append({
                "kind": kind,
                "label": _label(kind),
                "motivo": code,
                "current": current,
                "proposed": proposed,
                "n_feedback": len(evidence),
                "feedback_ids": [f.id for f in evidence],
            })
        return proposals

    # -- changes ----------------------------------------------------------------

    def apply(self, kinds: Optional[List[str]], admin_id: Optional[str]) -> Dict[str, Any]:
        """Apply the pending proposals for `kinds` (all if None). Recomputed
        here: the client says *which* to accept, never what the weight is."""
        proposals = {p["kind"]: p for p in self.propose()}
        if kinds is not None:
            unknown = [k for k in kinds if k not in DEFAULT_SOFT_WEIGHTS]
            if unknown:
                raise UnknownKind(f"Vincoli non regolabili: {', '.join(unknown)}")
            proposals = {k: p for k, p in proposals.items() if k in kinds}

        now = datetime.utcnow()
        for p in proposals.values():
            self.db.add(SoftWeightAdjustment(
                kind=p["kind"], old_weight=p["current"], new_weight=p["proposed"],
                evidenza={"motivo": p["motivo"], "feedback_ids": p["feedback_ids"]},
                admin_id=admin_id, created_at=now,
            ))
        self._audit("SOFT_WEIGHTS_APPLIED", admin_id, {
            p["kind"]: [p["current"], p["proposed"]] for p in proposals.values()
        })
        self.db.commit()
        return self.state()

    def reset(self, kind: Optional[str], admin_id: Optional[str]) -> Dict[str, Any]:
        """Back to the default weight for one kind (or all) - as a new row, so the history stays."""
        if kind is not None and kind not in DEFAULT_SOFT_WEIGHTS:
            raise UnknownKind(f"Vincolo non regolabile: {kind}")
        weights = self.active_weights()
        now = datetime.utcnow()
        changed: Dict[str, List[int]] = {}
        for k, default in DEFAULT_SOFT_WEIGHTS.items():
            if (kind is not None and k != kind) or weights[k] == default:
                continue
            self.db.add(SoftWeightAdjustment(
                kind=k, old_weight=weights[k], new_weight=default,
                evidenza={"reset": True}, admin_id=admin_id, created_at=now,
            ))
            changed[k] = [weights[k], default]
        if changed:
            self._audit("SOFT_WEIGHTS_RESET", admin_id, changed)
        self.db.commit()
        return self.state()

    def _audit(self, azione: str, admin_id: Optional[str], dettagli: Dict[str, Any]) -> None:
        if not dettagli:
            return
        from app.models import Scuola
        scuola = self.db.query(Scuola).first()
        if scuola is None:
            return
        self.db.add(AuditLog(scuola_id=scuola.id, azione=azione, admin_id=admin_id, dettagli=dettagli))

    # -- read model -------------------------------------------------------------

    def state(self) -> Dict[str, Any]:
        weights = self.active_weights()
        history = (
            self.db.query(SoftWeightAdjustment)
            .order_by(SoftWeightAdjustment.created_at.desc())
            .limit(20)
            .all()
        )
        return {
            "weights": [
                {"kind": k, "label": _label(k), "default": d, "current": weights[k]}
                for k, d in DEFAULT_SOFT_WEIGHTS.items()
            ],
            "proposals": self.propose(),
            "history": [
                {
                    "kind": h.kind, "label": _label(h.kind),
                    "old_weight": h.old_weight, "new_weight": h.new_weight,
                    "reset": bool((h.evidenza or {}).get("reset")),
                    "created_at": h.created_at.isoformat() if h.created_at else None,
                }
                for h in history
            ],
        }
