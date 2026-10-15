"""Test separato (nessuna modifica al solver): varianti del MODELLO per il target ore settimanale.

Ogni variante risolve un modello leggermente diverso; la sua soluzione viene poi RIVALUTATA con il modello
di produzione (solve_fixed) cosi' i risultati sono confrontabili sulla stessa metrica.

Uso: python solver_model_variants.py <week_start> <secondi> <out.jsonl> [variante ...]
Il testo di `_soft_ore_target_deviation` viene preso dal codice reale e modificato con sostituzioni di stringa.
"""
import collections, inspect, json, sys, textwrap, time
sys.path.insert(0, ".")
from datetime import date
from ortools.sat.python import cp_model
import app.domain.solver as solver_mod
from app.database import SessionLocal
from app.models import OrarioSettimanale, SlotLezione
from app.repositories.schedule import ScheduleRepository
from app.services.soft_weights import SoftWeightService
from app.domain.solver import ScheduleSolver

WEEK = date.fromisoformat(sys.argv[1]); T = float(sys.argv[2]); OUT = sys.argv[3]; ONLY = sys.argv[4:]
GIORNI = ["LUNEDI", "MARTEDI", "MERCOLEDI", "GIOVEDI", "VENERDI"]

SRC = textwrap.dedent(inspect.getsource(ScheduleSolver._soft_ore_target_deviation))


def make_target_fn(tol=0, prorate=False):
    src = SRC
    if tol:
        a = "self.model.Add(deviation >= ore_assigned - ore_target)"
        b = "self.model.Add(deviation >= ore_target - ore_assigned)"
        assert a in src and b in src
        src = src.replace(a, f"self.model.Add(deviation >= ore_assigned - ore_target - {tol})")
        src = src.replace(b, f"self.model.Add(deviation >= ore_target - ore_assigned - {tol})")
    if prorate:
        a = "ore_target = max(1, int(asg.ore_residue // weeks_asg))\n"
        assert src.count(a) >= 1
        src = src.replace(a, a + "        ore_target = max(1, round(ore_target * self._scale.get(asg.classe_id, 1.0)))\n", 1)
    ns = {}
    exec(src, vars(solver_mod), ns)
    return ns["_soft_ore_target_deviation"]


class Variant(ScheduleSolver):
    _scale = {}

    def _compute_scale(self):
        """Target di ogni classe riportati alla sua capienza settimanale (le aule vanno riempite al 100%)."""
        weeks = max(1, (self.context.anno_fine - self.context.week_start).days // 7)
        tot, cap = collections.Counter(), {}
        for a in self.context.assegnazioni:
            if a.ore_residue <= 0:
                continue
            tot[a.classe_id] += max(1, int(a.ore_residue // self._settimane_utili(a.classe_id, weeks)))
            cap.setdefault(a.classe_id, sum(self._ore_max_for_classe_giorno(a.classe_id, g) for g in range(5)))
        self._scale = {c: min(1.0, cap[c] / tot[c]) for c in tot if tot[c] > 0}

    def build_model(self):
        self._compute_scale()
        return super().build_model()


def build(ctx, w, tol=0, prorate=False):
    cls = type("V", (Variant,), {"_soft_ore_target_deviation": make_target_fn(tol, prorate)})
    s = cls(ctx, soft_weights=w)
    s.build_model()
    return s


def prod(ctx, w):
    s = ScheduleSolver(ctx, soft_weights=w)
    s.build_model()
    return s


class Trace(cp_model.CpSolverSolutionCallback):
    def __init__(self):
        super().__init__(); self.t0 = time.time(); self.pts = []

    def on_solution_callback(self):
        self.pts.append((round(time.time() - self.t0, 1), self.ObjectiveValue()))


def search(s, secs, extra=None, hint=None):
    if hint:
        for v, val in hint.items():
            s.model.AddHint(v, val)
    sol = cp_model.CpSolver()
    p = sol.parameters; p.max_time_in_seconds = secs; p.num_workers = 16
    for k, v in (extra or {}).items():
        setattr(p, k, v)
    cb = Trace(); t = time.time()
    st = sol.Solve(s.model, cb)
    return sol, st, cb.pts, round(time.time() - t, 1)


def evaluate(ctx, w, keys):
    """Rivaluta una soluzione con il modello di produzione."""
    s = prod(ctx, w)
    for k, v in s.x.items():
        s.model.Add(v == (1 if k in keys else 0))
    sol = cp_model.CpSolver(); sol.parameters.max_time_in_seconds = 30
    st = sol.Solve(s.model)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return {"eval": sol.StatusName(st)}
    n, wt = collections.Counter(), collections.Counter()
    for p in s.soft_penalties:
        if sol.Value(p.var):
            n[p.kind] += 1; wt[p.kind] += sol.Value(p.var) * p.weight
    return {"eval": "ok", "obj": sol.ObjectiveValue(), "n": dict(n), "peso": dict(wt)}


def hint_from_draft(db, ctx, s):
    """Hint dalla bozza gia' salvata della stessa settimana (caso 'rigenero dopo una piccola modifica')."""
    row = db.query(OrarioSettimanale).filter_by(settimana_inizio=WEEK).first()
    if not row:
        return None
    by = {(a.docente_id, a.classe_id, a.materia_id): a.assegnazione_id for a in ctx.assegnazioni}
    on = set()
    for sl in db.query(SlotLezione).filter_by(orario_settimanale_id=row.id).all():
        aid = by.get((sl.docente_id, sl.classe_id, sl.materia_id))
        g = GIORNI.index(str(getattr(sl.giorno, "name", sl.giorno)).upper())
        if aid:
            on.add((aid, g, sl.ora_inizio - 8))
    return {v: (1 if k in on else 0) for k, v in s.x.items()}


def run(name, db, ctx, w):
    extra, hint, tol, pro = {}, False, 0, False
    if name == "produzione": pass
    elif name == "tolleranza1": tol = 1
    elif name == "target_su_capienza": pro = True
    elif name == "capienza+tolleranza": pro, tol = True, 1
    elif name == "gap2pct": extra = {"relative_gap_limit": 0.02}
    elif name == "hint_bozza": hint = True
    elif name == "combo_best": pro, tol, extra = True, 1, {"linearization_level": 2}
    else: raise SystemExit(name)
    s = build(ctx, w, tol, pro)
    h = hint_from_draft(db, ctx, s) if hint else None
    sol, st, pts, secs = search(s, T, extra, h)
    rec = dict(week=str(WEEK), variant=name, status=sol.StatusName(st), secs=secs, own_obj=sol.ObjectiveValue(),
               bound=sol.BestObjectiveBound(), first=pts[0] if pts else None, last=pts[-1] if pts else None,
               t_5pct=next((t for t, o in pts if o <= pts[-1][1] * 1.05), None))
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        keys = {k for k, v in s.x.items() if sol.Value(v)}
        rec.update(evaluate(ctx, w, keys))
    return rec


NAMES = ["produzione", "tolleranza1", "target_su_capienza", "capienza+tolleranza", "gap2pct", "hint_bozza", "combo_best"]
if __name__ == "__main__":
    db = SessionLocal()
    ctx = ScheduleRepository(db).get_week_context("sch_1", WEEK)
    w = SoftWeightService(db).active_weights()
    for n in NAMES:
        if ONLY and n not in ONLY:
            continue
        try:
            rec = run(n, db, ctx, w)
        except Exception as e:  # noqa
            rec = dict(week=str(WEEK), variant=n, error=repr(e)[:300])
        print(json.dumps(rec), flush=True)
        open(OUT, "a").write(json.dumps(rec) + "\n")
