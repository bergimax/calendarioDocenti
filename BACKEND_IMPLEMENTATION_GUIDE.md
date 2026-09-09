# Backend Implementation Guide

## Struttura Creata

```
app/
├── config.py              # Configurazione (settings, env vars)
├── database.py            # Setup SQLAlchemy + engine
├── models.py              # 16 tabelle SQLAlchemy (Scuola, Classe, Docente, ...)
├── schemas.py             # Pydantic models (serializzazione/validazione)
├── main.py                # FastAPI app + router include
├── repositories/
│   ├── availability.py    # Data access per disponibilità
│   └── setup.py          # Data access per setup
└── routes/
    ├── availability.py   # GET/POST /api/availability/*
    ├── setup.py         # POST /api/calendar/upload, /api/setup/*
    ├── schedule.py      # POST /api/schedule/generate, /api/schedule/*/modify-slot, etc
    └── chat.py          # POST /api/chat/send (SSE stream)

requirements.txt           # Dipendenze (FastAPI, SQLAlchemy, OR-Tools, etc)
BACKEND_DESIGN.md         # Logica dettagliata (pseudocodice)
```

---

## Come Proseguire

### Fase 1: Database Setup (COMPLETATO ✓)
- ✓ SQLAlchemy models
- ✓ Pydantic schemas
- ✓ Database configuration
- ✓ Base repositories

### Fase 2: Routes Implementation (IN PROGRESS)

Endpoints completati con placeholders:
- ✓ `/api/availability/{week}/{teacher_id}` (GET)
- ✓ `/api/availability/{week}/{teacher_id}` (POST save)
- ✓ `/api/availability/{week}/copy-from/{prev_week}` (POST)
- ✓ `/api/availability/{week}/status` (GET)
- ✓ `/api/calendar/upload` (POST file)
- ✓ `/api/setup/validate` (POST)
- ✓ `/api/setup/validate-field` (POST)
- ✓ `/api/setup/save` (POST)
- ✓ `/api/schedule/generate` (POST)
- ✓ `/api/schedule/{week}` (GET)
- ✓ `/api/schedule/{week}/quality-score` (GET)
- ✓ `/api/schedule/{week}/modify-slot` (POST)
- ✓ `/api/schedule/{week}/approve` (POST)
- ✓ `/api/schedule/{week}/export-pdf` (GET)
- ✓ `/api/chat/send` (POST, SSE stream)
- ✓ `/api/chat/history/{week}` (GET)

**TODO:** Implementare logica dettagliata (attualmente solo placeholders con TODO)

### Fase 3: Services Layer (TODO)

Creare `app/services/` con business logic:

```python
# app/services/availability.py
class AvailabilityService:
    def get_or_create_availability(...)
    def copy_week_availability(...)

# app/services/setup.py
class SetupService:
    def validate_calendar_pdf(...)  # OCR + AI parsing
    def validate_all_files(...)
    def save_complete_setup(...)

# app/services/schedule.py
class ScheduleService:
    def generate_schedule(...)  # Chiama solver
    def recalculate_with_modifications(...)  # Warm start
    def calculate_quality_score(...)

# app/services/chat.py
class ChatService:
    def parse_admin_message(...)  # NLP + function calling
    def translate_to_constraints(...)
    def handle_chat_response(...)  # SSE
```

### Fase 4: Domain Logic (TODO)

Creare `app/domain/` con logica pura (no DB):

```python
# app/domain/solver.py
class ScheduleSolver:
    def build_or_tools_model(...)
    def add_hard_constraints(...)
    def add_soft_constraints(...)
    def solve(...)
    def extract_solution(...)

# app/domain/nlp.py
class ChatNLP:
    def parse_intent_with_llm(...)
    def validate_intent(...)
    def translate_to_constraints(...)

# app/domain/parser.py
class CalendarParser:
    def extract_text_from_pdf(...)  # OCR
    def parse_dates(...)
    def parse_stages(...)
    def ai_assisted_parsing(...)  # LLM

# app/domain/validator.py
class DataValidator:
    def validate_schedule(...)
    def check_coherence(...)
    def identify_conflicts(...)
```

### Fase 5: Integration (TODO)

- Implementare auth/context (get_current_school_id, admin_id)
- Setup PostgreSQL database
- Configurare .env
- Test endpoints

---

## Setup Environment

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create .env file
cat > .env <<EOF
DATABASE_URL=postgresql://user:password@localhost/calendariodocenti
ANTHROPIC_API_KEY=sk-...
DEBUG=True
SOLVER_TIMEOUT_SECONDS=60
EOF

# 3. Create PostgreSQL database
createdb calendariodocenti

# 4. Run migrations (create tables)
python -c "from app.database import engine; from app.models import Base; Base.metadata.create_all(bind=engine)"

# 5. Start server
uvicorn app.main:app --reload --port 8000
```

---

## Architettura Layers

```
┌──────────────────────────────────────────┐
│  FastAPI Routes (app/routes/*.py)        │ ← HTTP endpoints
├──────────────────────────────────────────┤
│  Services (app/services/*.py)            │ ← Orchestration
├──────────────────────────────────────────┤
│  Domain Logic (app/domain/*.py)          │ ← Solver, NLP, Parser
├──────────────────────────────────────────┤
│  Repositories (app/repositories/*.py)    │ ← Data access (DB queries)
├──────────────────────────────────────────┤
│  Models (app/models.py)                  │ ← SQLAlchemy ORM
├──────────────────────────────────────────┤
│  PostgreSQL Database                     │ ← Persistent storage
└──────────────────────────────────────────┘
```

---

## Implementazione Prioritari

**Raccomandazione:** Implementare in questo ordine:

1. **Availability Service** (semplice, isolato)
   - GET/POST availability
   - Copy previous week
   - No external dependencies

2. **Setup Service** (moderato, OCR required)
   - File upload
   - Calendar PDF parsing (OCR)
   - CSV parsing + validation
   - Transazione DB salvataggio

3. **Solver Service** (complesso, OR-Tools)
   - Build OR-Tools model
   - Add hard/soft constraints
   - Solve
   - Extract solution + quality score

4. **Chat Service** (LLM dependent)
   - Parse intent (Claude API)
   - Translate to constraints
   - Call solver warm-start
   - SSE response streaming

5. **Export Service** (semplice, WeasyPrint)
   - Generate HTML table
   - Render to PDF

---

## Testing Strategy

```python
# app/tests/test_availability.py
def test_get_default_availability_for_new_teacher():
    # Test GET /api/availability without prior record
    # Should return default grid (8-14)

def test_inherit_availability_for_recurring_teacher():
    # Test GET /api/availability for teacher with prior week
    # Should inherit from previous week

def test_save_availability():
    # Test POST /api/availability
    # Should save and mark teacher as "not first time"

def test_copy_week_availability():
    # Test POST /api/availability/{week}/copy-from/{prev_week}
    # Should copy all teachers' availability
```

---

## TODO Checklist

### Routes (Top Priority)
- [ ] Implement full `/api/availability/*` logic
- [ ] Implement full `/api/setup/*` logic
- [ ] Implement full `/api/schedule/*` logic
- [ ] Implement full `/api/chat/*` logic (SSE)

### Services (Mid Priority)
- [ ] Create `AvailabilityService`
- [ ] Create `SetupService` (with OCR)
- [ ] Create `ScheduleService` (with solver)
- [ ] Create `ChatService` (with LLM)

### Domain (High Priority)
- [ ] Create `ScheduleSolver` (OR-Tools integration)
- [ ] Create `ChatNLP` (LLM integration)
- [ ] Create `CalendarParser` (PDF OCR)
- [ ] Create `DataValidator` (cross-validation)

### Integration (Low Priority)
- [ ] Setup PostgreSQL
- [ ] Setup auth context
- [ ] Test endpoints
- [ ] Setup logging
- [ ] Setup error handling

---

## Key Implementation Notes

### Availability Module
- Default grid: 8-14 (08:00-09:00, 09:00-10:00, ..., 13:00-14:00)
- JSONB storage: `{"lunedi": [...], "martedi": [...], ...}`
- First-time logic: Check `docente.first_time_this_year` flag

### Setup Module
- OCR: Use PyPDF2 + Claude API for intelligent parsing
- Validation: Real-time field validation as admin types
- Transaction: Use `db.session.begin_nested()` for rollback safety
- Cache: Store parsed data in temp files/Redis during setup flow

### Solver Module
- Time limit: 60 seconds
- Warm start: When modifying existing schedule, start from current solution
- Quality score: % soft constraints satisfied
- Hard constraints: Enforce (infeasible if violated)
- Soft constraints: Minimize violations

### Chat Module
- Parser: LLM function calling to extract intent
- SSE: Stream real-time responses (thinking → suggestion → ready)
- Constraint translation: Convert intent to mathematical constraints
- Solver call: Use warm-start for fast recalculation

---

## Performance Considerations

- **Index on availability:** `(scuola_id, settimana_inizio, docente_id)`
- **Lazy loading:** Use `joinedload` to prevent N+1 queries
- **Caching:** Cache teacher availability (TTL 24h)
- **Batch operations:** Bulk insert slots (100 at a time)
- **Async:** Use async/await for long-running operations (solver, OCR)

