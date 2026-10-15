"""Benchmark di strategie di ricerca CP-SAT sullo stesso modello (sola lettura sul DB).

Uso: .venv/bin/python bench.py <week_start> <secondi> <out.jsonl> [variante ...]
Il modello e' identico per tutte le varianti (ScheduleSolver.build_model), cosi'
l'obiettivo e' direttamente confrontabile. Cambia solo COME si cerca.
"""
import json, sys, time, collections
sys.path.insert(0, ".")
from datetime import date
from ortools.sat.python import cp_model
from app.database import SessionLocal
from app.repositories.schedule import ScheduleRepository
from app.services.soft_weights import SoftWeightService
from app.domain.solver import ScheduleSolver

WEEK = date.fromisoformat(sys.argv[1])
T = float(sys.argv[2])
OUT = sys.argv[3]
ONLY = sys.argv[4:]


class Trace(cp_model.CpSolverSolutionCallback):
    def __init__(self, t0):
        super().__init__()
        self.t0, self.points = t0, []

    def on_solution_callback(self):
        self.points.append((round(time.time() - self.t0, 2), self.ObjectiveValue()))


def fresh(db, ctx, weights, best_effort=False):
    s = ScheduleSolver(ctx, soft_weights=weights, best_effort=best_effort)
    s.build_model()
    return s


def run_search(s, secs, workers=16, hint=None, extra=None, seed=None, bound_le=None):
    m = s.model
    if hint:
        m.ClearHints()
        for v, val in hint.items():
            m.AddHint(v, val)
    sol = cp_model.CpSolver()
    p = sol.parameters
    p.max_time_in_seconds = secs
    p.num_workers = workers
    if seed is not None:
        p.random_seed = seed
    for k, v in (extra or {}).items():
        setattr(p, k, v)
    cb = Trace(time.time())
    st = sol.Solve(m, cb)
    return sol, st, cb.points


def values(s, sol):
    return {v: sol.Value(v) for v in s.x.values()}


def full_values(s, sol):
    # hint su TUTTE le variabili del modello (x + ausiliarie)
    proto = s.model.Proto()
    return {s.model.GetBoolVarFromProtoIndex(i) if False else i: sol.Value(s.model.GetIntVarFromProtoIndex(i))
            for i in range(len(proto.variables))}


def breakdown(s, sol):
    d = collections.Counter()
    for p in s.soft_penalties:
        if sol.Value(p.var):
            d[p.kind] += 1 if p.var is not None else 0
    return dict(d)


def unfilled(s, sol):
    return sum(1 for p in s.soft_penalties if p.kind.startswith("classe_unfilled") and sol.Value(p.var))


# ---------------------------------------------------------------- varianti
def v_baseline(db, ctx, w):
    """Come in produzione oggi: parametri di default, 16 worker."""
    s = fresh(db, ctx, w)
    sol, st, pts = run_search(s, T)
    return s, sol, st, pts


def v_baseline_bis(db, ctx, w):
    """Ripetizione della baseline: misura il rumore tra run."""
    s = fresh(db, ctx, w)
    return (s, *run_search(s, T))


def v_workers8(db, ctx, w):
    s = fresh(db, ctx, w)
    return (s, *run_search(s, T, workers=8))


def v_lin2(db, ctx, w):
    s = fresh(db, ctx, w)
    return (s, *run_search(s, T, extra={"linearization_level": 2}))


def v_lin0(db, ctx, w):
    s = fresh(db, ctx, w)
    return (s, *run_search(s, T, extra={"linearization_level": 0}))


def v_portfolio_lns(db, ctx, w):
    """Piu' risorse sull'LNS (miglioramento locale) e meno sul bound."""
    s = fresh(db, ctx, w)
    return (s, *run_search(s, T, extra={"use_lns_only": True}))


def v_no_presolve_probing(db, ctx, w):
    s = fresh(db, ctx, w)
    return (s, *run_search(s, T, extra={"cp_model_probing_level": 0, "symmetry_level": 0}))


def v_symmetry2(db, ctx, w):
    s = fresh(db, ctx, w)
    return (s, *run_search(s, T, extra={"symmetry_level": 2}))


def v_core_off(db, ctx, w):
    s = fresh(db, ctx, w)
    return (s, *run_search(s, T, extra={"optimize_with_core": False, "optimize_with_lb_tree_search": False}))


def v_core(db, ctx, w):
    s = fresh(db, ctx, w)
    return (s, *run_search(s, T, extra={"optimize_with_core": True}))


def v_seeds4(db, ctx, w):
    """Campionamento: 4 seed x T/4, tiene la migliore."""
    best = None
    pts_all = []
    t0 = time.time()
    for seed in (1, 2, 3, 4):
        s = fresh(db, ctx, w)
        sol, st, pts = run_search(s, T / 4, seed=seed)
        pts_all += [(round(a + (seed - 1) * T / 4, 2), b) for a, b in pts]
        if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            if best is None or sol.ObjectiveValue() < best[1].ObjectiveValue():
                best = (s, sol, st)
    if best is None:
        return s, sol, st, pts_all
    return best[0], best[1], best[2], pts_all


def _hint_all(s, sol):
    return {s.model.GetIntVarFromProtoIndex(i): sol.Value(s.model.GetIntVarFromProtoIndex(i))
            for i in range(len(s.model.Proto().variables))}


def v_two_phase(db, ctx, w):
    """Fase 1 (50% del tempo): minimizza solo le regole quasi-rigide (peso>=500: deroghe, ore esatte,
    ore scoperte). Fase 2: obiettivo completo con la fase 1 come tetto + hint."""
    s = fresh(db, ctx, w)
    crit = [p for p in s.soft_penalties if p.weight >= 500]
    full = sum(p.var * p.weight for p in s.soft_penalties)
    crit_expr = sum(p.var * p.weight for p in crit)
    s.model.clear_objective()
    s.model.Minimize(crit_expr)
    sol1, st1, pts1 = run_search(s, T * 0.5)
    if st1 not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return s, sol1, st1, pts1
    best_crit = round(sol1.ObjectiveValue())
    hint = _hint_all(s, sol1)
    s.model.Add(crit_expr <= best_crit)
    s.model.clear_objective()
    s.model.Minimize(full)
    sol2, st2, pts2 = run_search(s, T * 0.5, hint=hint)
    pts = pts1 + [(round(a + T * 0.5, 2), b) for a, b in pts2]
    if st2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return s, sol2, st2, pts
    return s, sol1, st1, pts


VARIANTS = {k[2:]: f for k, f in globals().items() if k.startswith("v_")}

if __name__ == "__main__":
    db = SessionLocal()
    ctx = ScheduleRepository(db).get_week_context("sch_1", WEEK)
    w = SoftWeightService(db).active_weights()
    for name, fn in VARIANTS.items():
        if ONLY and name not in ONLY:
            continue
        t = time.time()
        try:
            s, sol, st, pts = fn(db, ctx, w)
            ok = st in (cp_model.OPTIMAL, cp_model.FEASIBLE)
            rec = dict(week=str(WEEK), variant=name, status=sol.StatusName(st), secs=round(time.time() - t, 1),
                       obj=sol.ObjectiveValue() if ok else None,
                       bound=sol.BestObjectiveBound() if ok else None,
                       first=pts[0] if pts else None, last=pts[-1] if pts else None, nsol=len(pts),
                       by_kind=breakdown(s, sol) if ok else None)
        except Exception as e:  # noqa
            rec = dict(week=str(WEEK), variant=name, error=repr(e)[:300])
        print(json.dumps(rec), flush=True)
        open(OUT, "a").write(json.dumps(rec) + "\n")
