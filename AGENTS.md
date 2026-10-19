# AGENTS.md — Calendario Docenti

Web platform that generates, reviews and publishes the **weekly timetable** of a
vocational training school. A CP-SAT constraint solver (Google OR-Tools) builds one
week at a time; an admin reviews, adjusts, approves and exports it (PDF/Excel).

Live demo: https://130-110-14-231.sslip.io (login required). Docs are in English;
the product UI and the domain vocabulary (docente, classe, orario, deroga…) are Italian.

## Stack

- Backend: Python 3.13, FastAPI, SQLAlchemy 2.0, OR-Tools CP-SAT, WeasyPrint (`app/`)
- Frontend: React 19, TanStack Start/Router/Query, Tailwind 4 (`frontend/`)
- Database: PostgreSQL 15 in production, SQLite in dev/tests
- Ops: Docker Compose + Caddy (`deploy/`), GitHub Actions (`.github/workflows/`),
  Prometheus + Grafana + Loki + Tempo (`observability/`)

## Commands

| Task | Command |
|---|---|
| Run the whole stack locally (DB + backend + frontend) | `make up` |
| Run all tests (unit + integration) | `make test` |
| Unit tests only / integration tests only | `make test-unit` / `make test-integration` |
| Typecheck + build the frontend | `make frontend-check` |
| Backend without Docker | `.venv/bin/uvicorn app.main:app --reload` |

Always use `.venv/bin/python` (system Python). Anaconda's Python segfaults with ortools.

## Repository map

```
app/domain/        pure logic: solver.py, parser.py, validator.py, soft_weights.py, nlp.py
app/services/      business logic orchestrated by routes
app/repositories/  DB access
app/routes/        FastAPI endpoints (prefix /api)
app/observability.py  structured logs, metrics, traces (see docs/observability.md)
frontend/src/      routes (pages), lib/api.ts (HTTP client)
tests/             pytest: unit (test_solver, test_validator, ...) and API integration (test_api_*)
scripts/           one-off admin/data scripts
deploy/            production compose helpers, Caddyfile, backups
observability/     collector, Prometheus, Grafana, Loki, Tempo, alert rules
```

## Hard rules for agents

1. **Never commit real school data** (DB copies, dumps, real PDFs/Excel). The repo is
   public. Stage files explicitly (`git add <path>`), never `git add -A`.
2. Never put personal data (teacher names, emails) or secrets in logs, metrics or traces.
3. Every behaviour change needs a test; bug fixes need a regression test.
4. Work from a GitHub issue; reference it in the commit/PR (`Closes #N`) and meet its
   acceptance criteria before closing it.
5. Production deploys are manual (approval gate). Do not bypass CI.
6. Ask before destructive or outward-facing actions (force push, deleting data, deploys).

## Modular docs (read what the task needs)

| Doc | Read it when |
|---|---|
| [docs/process.md](docs/process.md) | starting any task: workflow from issue to deploy |
| [docs/agent-team.md](docs/agent-team.md) | deciding which agent role does what |
| [docs/architecture.md](docs/architecture.md) | touching the backend, frontend or data model |
| [docs/testing.md](docs/testing.md) | writing or running tests |
| [docs/deployment.md](docs/deployment.md) | CI/CD, environments, production |
| [docs/observability.md](docs/observability.md) | logs, metrics, traces, alerts |
| [docs/oncall-agent.md](docs/oncall-agent.md) | an alert fired / working as the on-call agent |
| [specs.md](specs.md) | exact functional spec (formulas, solver constraints, data model) |
| [SPECIFICHE_SOLVER.md](SPECIFICHE_SOLVER.md) | solver rules in detail (Italian) |
