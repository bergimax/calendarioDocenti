# Quick Start: Backend Testing Guide

**Goal:** Verify backend is working before starting frontend

---

## 1. Setup & Run Backend

### Prerequisites
```bash
# Check Python version
python3 --version  # Should be 3.10+

# Check if dependencies installed
pip list | grep -E "fastapi|sqlalchemy|ortools|anthropic"
```

### Start Server
```bash
# From project root
cd /home/bergimax/Projects/calendarioDocenti

# Start FastAPI server (with auto-reload for development)
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

**Expected Output:**
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete
```

### Check Server is Alive
```bash
curl http://localhost:8000/health
# Should return: {"status":"ok"}
```

---

## 2. Explore API Documentation

Open browser: **http://localhost:8000/docs**

You should see:
- Interactive Swagger UI
- All endpoints listed
- Try-it-out buttons for each endpoint
- Request/response schemas

---

## 3. Test Each Service (Manual Flow)

### A. Test AvailabilityService

**Step 1: Get default availability grid**
```bash
curl -X GET "http://localhost:8000/availability/teacher_1/week?week_start=2026-09-08"
```

**Expected Response:**
```json
{
  "status": "found",
  "availability": {
    "giorni_fasce": {
      "lunedi": [[true, true, true, true, true, true]],
      "martedi": [[true, true, true, true, true, true]],
      ...
    }
  }
}
```

**Step 2: Update availability (some slots unavailable)**
```bash
curl -X POST "http://localhost:8000/availability/teacher_1" \
  -H "Content-Type: application/json" \
  -d '{
    "week_start": "2026-09-08",
    "giorni_fasce": {
      "lunedi": [[false, true, true, true, true, true]],
      "martedi": [[true, true, true, false, true, true]],
      "mercoledi": [[true, true, true, true, true, true]],
      "giovedi": [[true, true, true, true, true, true]],
      "venerdi": [[true, true, true, true, true, true]]
    }
  }'
```

**Expected Response:**
```json
{
  "status": "saved",
  "week_start": "2026-09-08"
}
```

---

### B. Test SetupService (CSV Upload & Validation)

**Create sample CSV files:**

**calendario.csv**
```csv
giorno,ore_max_giornata,flag_chiusura,stage_classe_id
lunedi,6,false,
martedi,6,false,
mercoledi,6,false,
giovedi,6,false,
venerdi,6,false,
```

**docenti.csv**
```csv
nome,email,tipo
Rossi Mario,mario.rossi@example.com,ASSUNTO
Neri Angela,angela.neri@example.com,CONTRATTO
```

**classi.csv**
```csv
nome,n_studenti
2A,25
2B,28
3A,23
```

**materie.csv**
```csv
nome,tipo,peso_cognitivo
Inglese,TEORIA,ALTO
Laboratorio,PRATICA,MEDIO
Matematica,TEORIA,ALTO
```

**assegnazioni.csv**
```csv
docente_nome,classe_nome,materia_nome,ore_anno
Rossi Mario,2A,Inglese,66
Neri Angela,2A,Laboratorio,66
Rossi Mario,3A,Matematica,66
```

**accoppiamenti.csv**
```csv
classe_a,classe_b,materia_nome,note
2A,2B,Inglese,Lab together
```

**Step 1: Validate setup**
```bash
curl -X POST "http://localhost:8000/setup/validate" \
  -H "Content-Type: application/json" \
  -d '{
    "calendario": "giorno,ore_max_giornata,flag_chiusura,stage_classe_id\nlunedi,6,false,\n...",
    "docenti": "nome,email,tipo\nRossi Mario,mario.rossi@example.com,ASSUNTO\n...",
    "classi": "nome,n_studenti\n2A,25\n...",
    "materie": "nome,tipo,peso_cognitivo\nInglese,TEORIA,ALTO\n...",
    "assegnazioni": "docente_nome,classe_nome,materia_nome,ore_anno\nRossi Mario,2A,Inglese,66\n...",
    "accoppiamenti": "classe_a,classe_b,materia_nome,note\n2A,2B,Inglese,Lab together\n"
  }'
```

**Expected Response:**
```json
{
  "status": "valid",
  "preview": {
    "docenti_count": 2,
    "classi_count": 3,
    "materie_count": 3,
    "assegnazioni_count": 3,
    "accoppiamenti_count": 1
  },
  "errors": []
}
```

**Step 2: Save to database**
```bash
curl -X POST "http://localhost:8000/setup/save" \
  -H "Content-Type: application/json" \
  -d '{
    "school_name": "Liceo Scientifico",
    "school_year": "2026-2027",
    "data_inizio": "2026-09-01",
    "data_fine": "2027-06-30"
  }'
```

**Expected Response:**
```json
{
  "status": "saved",
  "school_id": "sch_1",
  "entities_created": {
    "docenti": 2,
    "classi": 3,
    "materie": 3,
    "assegnazioni": 3,
    "accoppiamenti": 1
  }
}
```

---

### C. Test ScheduleSolver (Generate Schedule)

**Step 1: Generate schedule**
```bash
curl -X POST "http://localhost:8000/schedule/generate?week_start=2026-09-08" \
  -H "Content-Type: application/json"
```

**Expected Response (OPTIMAL):**
```json
{
  "status": "generated",
  "schedule_id": "sch_1_2026-09-08",
  "quality_score": 87.5,
  "quality_level": "B",
  "slots": [
    {
      "slot_id": "...",
      "classe_id": "2A",
      "docente_id": "teacher_1",
      "materia_id": "Inglese",
      "giorno": "lunedi",
      "ora_inizio": 8,
      "ora_fine": 9,
      "accoppiata": false
    },
    ...
  ]
}
```

**If INFEASIBLE:**
```json
{
  "status": "infeasible",
  "conflicting_constraints": [
    "Teacher X: no feasible slot (ore_residue=0)",
    "Class Y: day capacity exceeded"
  ],
  "suggested_deroghe": [
    "Reduce expected hours for this assignment",
    "Extend teacher availability"
  ]
}
```

**Step 2: Get schedule**
```bash
curl -X GET "http://localhost:8000/schedule/2026-09-08"
```

**Expected Response:**
```json
{
  "status": "found",
  "schedule": {
    "schedule_id": "sch_1_2026-09-08",
    "stato": "BOZZA",
    "quality_score": 87.5,
    "quality_level": "B",
    "slots": [...]
  }
}
```

---

### D. Test ChatService (Intent Parsing + SSE)

**Step 1: Send chat message (SSE stream)**
```bash
curl -X POST "http://localhost:8000/chat/send" \
  -H "Content-Type: application/json" \
  -d '{
    "schedule_id": "sch_1_2026-09-08",
    "message": "Sposta inglese 2A da lunedi a martedi"
  }' \
  --stream
```

**Expected Response (SSE events):**
```
data: {"type": "thinking", "text": "Analizzando richiesta..."}

data: {"type": "suggestion", "text": "Ho capito: Sposta inglese di 2A da lunedi a martedi"}

data: {"type": "ready", "new_score": 89.2, "text": "Modifiche applicate. Qualità: 89%"}
```

**Step 2: Get chat history**
```bash
curl -X GET "http://localhost:8000/chat/history/sch_1_2026-09-08"
```

**Expected Response:**
```json
{
  "messages": [
    {
      "id": "msg_1",
      "role": "ADMIN",
      "text": "Sposta inglese 2A da lunedi a martedi",
      "timestamp": "2026-09-09T10:30:00"
    },
    {
      "id": "msg_2",
      "role": "AI",
      "text": "Ho registrato: Sposta inglese...",
      "timestamp": "2026-09-09T10:30:01"
    }
  ]
}
```

---

### E. Test Approval & Export

**Step 1: Approve schedule**
```bash
curl -X POST "http://localhost:8000/schedule/2026-09-08/approve"
```

**Expected Response:**
```json
{
  "status": "approved",
  "schedule_id": "sch_1_2026-09-08",
  "stato": "APPROVATO"
}
```

**Step 2: Export PDF**
```bash
curl -X GET "http://localhost:8000/schedule/2026-09-08/export-pdf" \
  -o orario_2026-09-08.pdf
```

**Expected Response:**
- Status: 200
- File downloaded as PDF (or placeholder message)

---

## 4. Database Verification

**Check if data was saved to DB:**

```bash
# If using SQLite (for testing)
sqlite3 app.db ".tables"
# Should show: scuole, docenti, classi, materie, etc.

# If using PostgreSQL
psql -U postgres -d calendario_db -c "\dt"
```

**Sample query:**
```sql
-- Check docenti saved
SELECT nome, tipo FROM docenti WHERE scuola_id='sch_1';

-- Check assegnazioni
SELECT docente_id, classe_id, materia_id FROM assegnazioni WHERE scuola_id='sch_1';

-- Check generated schedule
SELECT * FROM orario_settimanale WHERE scuola_id='sch_1' ORDER BY data_inizio DESC LIMIT 1;
```

---

## 5. Debugging

### Check Logs
```bash
# Watch API logs (in the terminal running uvicorn)
# Look for ERROR messages or DEBUG info
```

### Common Issues

**Issue:** `Port 8000 already in use`
```bash
# Kill process using port 8000
lsof -ti:8000 | xargs kill -9
```

**Issue:** `Database connection failed`
```bash
# Check DATABASE_URL in app/config.py
# Make sure PostgreSQL/SQLite is running
```

**Issue:** `Module not found: ortools`
```bash
# Install OR-Tools
pip install ortools
```

**Issue:** `CORS error in browser`
```bash
# Already configured in app/main.py
# If frontend is on different port, CORS should allow it
```

---

## 6. Next Steps: Start Frontend

Once all tests pass:

1. Create React/Next.js app
2. Point API to `http://localhost:8000`
3. Implement pages from FRONTEND_CHECKLIST.md
4. Test end-to-end workflow

---

**All tests passing? You're ready for frontend development! 🚀**
