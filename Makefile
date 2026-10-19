PY ?= .venv/bin/python
COMPOSE = docker compose -f docker-compose.local.yml

.PHONY: demo-data up down logs test test-unit test-integration frontend-check install

install:  ## Python venv + backend/test dependencies
	python3 -m venv .venv
	$(PY) -m pip install -r requirements-dev.txt

up:  ## Whole stack (Postgres + backend + frontend + proxy + observability) -> http://localhost:8080
	docker build -t calendario-backend:local .
	docker build -t calendario-frontend:local frontend
	$(COMPOSE) up -d --no-build
	@echo "App: http://localhost:8080 (admin@example.com / admin1234)   Grafana: http://localhost:3001"

demo-data:  ## Load a synthetic school and generate one timetable into the running stack
	$(PY) scripts/load_demo_data.py

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

test:  ## All tests (unit + integration)
	$(PY) -m pytest -q

test-unit:
	$(PY) -m pytest -q -m "not integration"

test-integration:
	$(PY) -m pytest -q -m integration

frontend-check:  ## Frontend typecheck + production build
	cd frontend && npm ci && npx tsc --noEmit && npm run build
