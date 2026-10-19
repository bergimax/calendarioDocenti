# Calendario Docenti — AI-assisted school timetabling

**Live demo:** https://130-110-14-231.sslip.io (login required; credentials on request)
· **Docs for agents:** [AGENTS.md](AGENTS.md) · **Specs:** [specs.md](specs.md)

> The UI and domain vocabulary are Italian (docente = teacher, classe = class,
> orario = timetable, deroga = waiver). All documentation is in English.

## The problem

A vocational training school (Italian *Agenzia Formativa*, IeFP / secondary level)
must publish a **weekly timetable** every week of the school year. Doing it by hand in
a spreadsheet takes hours and keeps breaking, because the rules interact:

- each teacher teaches several classes and has a **residual yearly hour budget** per class
  (*monte ore*) that must be consumed by the end of the year;
- part-time teachers are available only on certain days/hours, full-time teachers always;
- the **annual calendar** closes days, shortens days per year-group and sends classes on
  work placement (*stage*) — those classes must get no lessons;
- some lessons are taught to **two classes at once** (paired classes);
- practical lessons must come in blocks of at least 3 hours, no teacher should have idle
  gaps, Fridays must start at 08:00, etc.

## What the system does

1. **Guided setup**: the admin uploads the school data (CSV / the annual calendar PDF /
   teacher–class assignments); the system validates it and shows what needs fixing.
2. **Teacher availability** per week (grid), or inferred from past timetables.
3. **Timetable generation**: a CP-SAT constraint solver (Google OR-Tools) produces the
   week respecting all hard rules, and optimises weighted soft rules. If the rules are
   impossible to satisfy it says why; the admin can grant an explicit *deroga* (waiver)
   for one rule and regenerate.
4. **Review & edit**: quality score (A/B/C), itemised conflicts, move a lesson with live
   validation, approve the week.
5. **Export** the approved week as a PDF poster or Excel file.
6. **Learning from ratings**: the admin rates each week 1–5 with reasons; low ratings
   become *proposals* to raise the weight of the matching soft rule, approved by the admin.

Expected behaviour: given valid data, generating a week returns in under a minute a
timetable with **no double bookings, no lessons on closed/stage days and no teacher
outside their availability**; every remaining soft-rule violation is listed. Roles:
`ADMIN` (everything) and `SEGRETERIA` (read-only timetable + teacher availability).
Details: [specs.md](specs.md).

## Run it locally (one command)

Requires Docker with Compose v2.

```bash
make up          # builds and starts Postgres + backend + frontend + proxy + observability
```

| What | Where |
|---|---|
| App | http://localhost:8080 — demo login `admin@example.com` / `admin1234` |
| API docs | http://localhost:8080/docs |
| Grafana (metrics, traces, logs) | http://localhost:3001 (anonymous viewer) |

`make down` stops it. Data persists in a Docker volume.

### Without Docker

```bash
make install                                   # venv + dependencies
.venv/bin/uvicorn app.main:app --reload        # backend, SQLite via DATABASE_URL in .env
cd frontend && npm install && npm run dev      # frontend
```

Use `.venv/bin/python` (system Python): Anaconda's Python segfaults with OR-Tools.

## Tests

```bash
make test               # everything (unit + integration), no external services needed
make test-unit          # pure domain logic: solver, validator, parsers, auth
make test-integration   # real FastAPI app + SQLite through the HTTP API
```

See [docs/testing.md](docs/testing.md). CI runs the same command on every pull request.

## Architecture

```
Browser ─HTTPS→ Caddy ─/api→ FastAPI backend ─→ PostgreSQL
                     └─ /  → TanStack Start frontend (SSR)
backend ─OTLP→ OpenTelemetry Collector → Tempo · Prometheus · Loki → Grafana → alerts
```

- **Backend** `app/`: FastAPI, SQLAlchemy, OR-Tools CP-SAT solver, WeasyPrint PDF export
- **Frontend** `frontend/`: React 19, TanStack Router/Query, Tailwind
- **Deploy** `deploy/`: Docker Compose + Caddy (automatic HTTPS) on an Oracle Cloud VM

More in [docs/architecture.md](docs/architecture.md).

## Delivery pipeline (CI/CD)

- **CI** (`.github/workflows/ci.yml`): backend tests + frontend lint/build on every PR and push.
- **CD** (`.github/workflows/cd.yml`): merge to `master` → images built → **dev** deployed
  automatically → **production** deployed only after a manual approval.

See [docs/deployment.md](docs/deployment.md).

## Observability, alerting and on-call agent

The backend emits **metrics, traces and structured JSON logs that share one trace ID**
for the key user journey (*generate weekly timetable*), with no personal data. They are
stored in Prometheus/Tempo/Loki and browsable in Grafana. An alert on **user impact**
(timetable generation failing) wakes an **on-call agent** that investigates and opens a
fix pull request. See [docs/observability.md](docs/observability.md) and
[docs/oncall-agent.md](docs/oncall-agent.md).

## How the project is built (agentic workflow)

Work is specified as GitHub issues with acceptance criteria, implemented by a small team
of AI agents with defined roles, and merged through PRs that reference the issues. See
[docs/agent-team.md](docs/agent-team.md), [docs/process.md](docs/process.md) and the
[issue tracker](https://github.com/bergimax/calendarioDocenti/issues).

## Production

Step-by-step VM setup (Oracle Cloud Always Free, Docker Compose, Caddy HTTPS, backups):
[deploy/README.md](deploy/README.md) (Italian).

## Repository layout

```
app/            backend (routes → services → repositories / domain)
frontend/       web UI
tests/          unit + integration tests
deploy/         production compose helpers, Caddyfile, backups
observability/  OpenTelemetry collector, Prometheus, Loki, Tempo, Grafana, alert rules
oncall/         alert → on-call agent relay
docs/           process, team, architecture, testing, deployment, observability
specs.md        full functional specification (Italian)
```
