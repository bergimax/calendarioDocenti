# Testing

Two layers, both run by `make test` (also what CI runs):

| Layer | Files | What it covers | Command |
|---|---|---|---|
| Unit | `test_solver`, `test_validator`, `test_nlp`, `test_soft_weights`, `test_*_parser`, `test_auth_password`, `test_avvisi_ore`, `test_roles` | Pure domain logic, no HTTP | `make test-unit` |
| Integration | `test_api_*`, `test_setup_upload_flow`, `test_calendar_pdf_integration` | Real FastAPI app + SQLite DB through the HTTP API: setup → availability → generate → approve | `make test-integration` |

- Tests use a temporary SQLite file; no PostgreSQL needed. `tests/conftest.py` provides
  the API client (admin auth bypassed).
- Parsers are tested with synthetic PDFs (reportlab) — never commit real school files.
- A bug fix needs a regression test that fails before the fix.
- Frontend: `make frontend-check` (tsc + build) runs in CI.
