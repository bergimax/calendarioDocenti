# Architecture

```
Browser ──HTTPS──▶ Caddy ──/api/*, /health──▶ backend (FastAPI :8000) ──▶ PostgreSQL
                     └─────── everything else ─▶ frontend (Node SSR :3000)
backend ──OTLP──▶ otel-collector ──▶ Tempo (traces) · Prometheus (metrics) · Loki (logs) ──▶ Grafana
```

## Backend (`app/`)

Layered: `routes` (HTTP, validation) → `services` (orchestration) → `repositories`
(SQL) and `domain` (pure logic, no DB). The solver in `app/domain/solver.py` takes a
weekly context and returns slots; hard constraints are never violated, "relaxable-hard"
rules can be waived by an admin *deroga*, soft constraints are weighted
(`app/domain/soft_weights.py`, learned from admin ratings).

Auth: bearer-token sessions, roles ADMIN and SEGRETERIA (`app/security.py`).
Single tenant: `scuola_id = "sch_1"`.

## Frontend (`frontend/`)

TanStack Start (SSR) pages: login, menu, setup wizard, availability, timetable
(`orario`), school data CRUD (`dati.*`), account. All HTTP goes through
`frontend/src/lib/api.ts`.

## Data

16 tables, PostgreSQL in prod and SQLite in dev/tests. Schema is created with
`Base.metadata.create_all`; there is no Alembic, so a new column needs a small
migration function like `ensure_admin_role_column()` in `app/database.py`.
Key idea: an *assegnazione* is teacher + class + type (pair/single), with its own
monte ore (`ore_totali − ore_erogate` = residual hours).

Full details: [specs.md](../specs.md) §2–§12.
