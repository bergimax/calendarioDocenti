#!/usr/bin/env python3
"""Mock backend for frontend testing (while ortools issue is fixed)."""
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import json
import uuid
from datetime import datetime, timedelta
from io import StringIO

app = FastAPI(title="Calendario Docenti API (Mock)")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage
file_store = {}
validation_store = {}
teachers_store = {}
schedules_store = {}
chat_history = {}

# ============ SETUP ENDPOINTS ============

@app.post("/api/calendar/upload")
async def calendar_upload(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    content = await file.read()
    file_store[file_id] = {"type": "calendario", "name": file.filename, "content": content}
    return {"status": "uploaded", "file_id": file_id, "file_type": "calendario"}

@app.post("/api/teachers/upload")
async def teachers_upload(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    content = await file.read()
    file_store[file_id] = {"type": "docenti", "name": file.filename, "content": content}
    return {"status": "uploaded", "file_id": file_id, "file_type": "docenti"}

@app.post("/api/classes/upload")
async def classes_upload(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    content = await file.read()
    file_store[file_id] = {"type": "classi", "name": file.filename, "content": content}
    return {"status": "uploaded", "file_id": file_id, "file_type": "classi"}

@app.post("/api/subjects/upload")
async def subjects_upload(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    content = await file.read()
    file_store[file_id] = {"type": "materie", "name": file.filename, "content": content}
    return {"status": "uploaded", "file_id": file_id, "file_type": "materie"}

@app.post("/api/assignments/upload")
async def assignments_upload(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    content = await file.read()
    file_store[file_id] = {"type": "assegnazioni", "name": file.filename, "content": content}
    return {"status": "uploaded", "file_id": file_id, "file_type": "assegnazioni"}

@app.post("/api/class-pairings/upload")
async def pairings_upload(file: UploadFile = File(...)):
    file_id = str(uuid.uuid4())
    content = await file.read()
    file_store[file_id] = {"type": "accoppiamenti", "name": file.filename, "content": content}
    return {"status": "uploaded", "file_id": file_id, "file_type": "accoppiamenti"}

@app.post("/api/setup/validate")
async def setup_validate(body: dict):
    """Validate all uploaded files."""
    file_ids = body.get("file_ids", [])
    results = {}
    for fid in file_ids:
        if fid in file_store:
            ftype = file_store[fid]["type"]
            results[ftype] = {
                "success": True,
                "preview": {"count": 5, "rows": "5 rows parsed"},
                "warnings": [],
                "errors": []
            }
    validation_store["latest"] = results
    return {
        "status": "validation_complete",
        "results": results,
        "overall_status": "valid",
        "can_proceed": len(results) >= 6
    }

@app.post("/api/setup/validate-field")
async def validate_field(body: dict):
    """Validate single field correction."""
    return {"valid": True, "message": "Campo validato correttamente"}

@app.post("/api/setup/save")
async def setup_save(body: dict):
    """Save setup and create school."""
    school_id = f"sch_{uuid.uuid4().hex[:8]}"
    return {
        "status": "saved",
        "school_id": school_id,
        "entities_created": {
            "docenti": 10,
            "classi": 5,
            "materie": 8,
            "assegnazioni": 25,
            "accoppiamenti": 3
        }
    }

@app.post("/api/calendar/add-date-manual")
async def add_calendar_date(body: dict):
    """Add manual calendar date (OCR fallback)."""
    return {"status": "added", "total_dates_loaded": 180}

# ============ AVAILABILITY ENDPOINTS ============

@app.get("/api/availability/weeks")
async def get_weeks():
    """Get available weeks."""
    today = datetime.now()
    weeks = []
    for i in range(40):
        start = today + timedelta(weeks=i)
        if start.weekday() != 0:
            start = start - timedelta(days=start.weekday())
        end = start + timedelta(days=4)
        weeks.append({
            "start": start.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
            "week_num": i + 1
        })
    return {"weeks": weeks}

@app.get("/api/teachers")
async def get_teachers():
    """Get all teachers."""
    return [
        {"teacher_id": "doc_1", "nome": "Mario Rossi", "email": "rossi@scuola.it", "tipo": "ASSUNTO"},
        {"teacher_id": "doc_2", "nome": "Angela Neri", "email": "neri@scuola.it", "tipo": "CONTRATTISTA"},
        {"teacher_id": "doc_3", "nome": "Francesco Bianchi", "email": "bianchi@scuola.it", "tipo": "ASSUNTO"},
        {"teacher_id": "doc_4", "nome": "Sara Verdi", "email": "verdi@scuola.it", "tipo": "CONTRATTISTA"},
        {"teacher_id": "doc_5", "nome": "Marco Gallo", "email": "gallo@scuola.it", "tipo": "ASSUNTO"},
    ]

@app.get("/api/availability/{week}/{teacher_id}")
async def get_availability(week: str, teacher_id: str):
    """Get teacher availability for week."""
    # Return empty grid
    slot_template = [
        {"ora_inizio": f"{h:02d}:00", "ora_fine": f"{h+1:02d}:00", "disponibile": True}
        for h in range(8, 14)
    ]
    return {
        "teacher_id": teacher_id,
        "week_start": week,
        "giorni_fasce": {
            "lunedi": slot_template,
            "martedi": slot_template,
            "mercoledi": slot_template,
            "giovedi": slot_template,
            "venerdi": slot_template,
        }
    }

@app.post("/api/availability/{week}/{teacher_id}")
async def save_availability(week: str, teacher_id: str, body: dict):
    """Save teacher availability."""
    return {"status": "saved", "week_start": week}

@app.post("/api/availability/{week}/copy-from/{prev_week}")
async def copy_availability(week: str, prev_week: str):
    """Copy availability from previous week."""
    return {"teachers_copied": 5}

@app.get("/api/availability/{week}/status")
async def availability_status(week: str):
    """Get availability completion status."""
    return {
        "week_complete": False,
        "total_teachers": 5,
        "teachers_with_availability": 2,
        "ready_to_generate": True
    }

# ============ SCHEDULE ENDPOINTS ============

@app.post("/api/schedule/generate")
async def generate_schedule(body: dict):
    """Generate optimal schedule."""
    schedule_id = f"sch_{uuid.uuid4().hex[:8]}"

    # Create mock schedule
    slots = []
    classes = ["1A", "1B", "2A", "2B", "3A"]
    teachers = ["doc_1", "doc_2", "doc_3", "doc_4"]
    subjects = ["Matematica", "Inglese", "Italiano", "Scienze"]
    days = ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi"]
    hours = ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00"]

    slot_id = 0
    for day_idx, day in enumerate(days):
        for hour_idx, hour in enumerate(hours[:-1]):
            for class_idx, classe in enumerate(classes):
                if (slot_id + class_idx + day_idx + hour_idx) % 3 == 0:  # Mock assignment
                    slots.append({
                        "slot_id": f"slot_{slot_id}",
                        "classe_id": classe,
                        "classe_nome": classe,
                        "docente_id": teachers[slot_id % len(teachers)],
                        "docente_nome": ["Mario Rossi", "Angela Neri", "Francesco Bianchi", "Sara Verdi"][slot_id % 4],
                        "materia_id": subjects[slot_id % len(subjects)],
                        "materia_nome": subjects[slot_id % len(subjects)],
                        "giorno": day,
                        "ora_inizio": hour,
                        "ora_fine": hours[hour_idx + 1],
                        "tipologia": "TEORIA" if slot_id % 2 == 0 else "PRATICA",
                        "accoppiata": False,
                        "conflitto": False
                    })
                    slot_id += 1

    schedules_store[schedule_id] = {"slots": slots, "quality_score": 85, "quality_level": "B", "stato": "BOZZA"}

    return {
        "status": "generated",
        "schedule_id": schedule_id,
        "quality_score": 85,
        "quality_level": "B",
        "slots": slots[:20],  # Return first 20
        "conflicts": []
    }

@app.get("/api/schedule/{week}")
async def get_schedule(week: str):
    """Get existing schedule."""
    if not schedules_store:
        return {"status": "not_found"}

    schedule = list(schedules_store.values())[0]
    return {
        "status": "found",
        "schedule_id": "sch_latest",
        "quality_score": schedule.get("quality_score", 85),
        "quality_level": schedule.get("quality_level", "B"),
        "stato": schedule.get("stato", "BOZZA"),
        "slots": schedule.get("slots", []),
        "conflicts": [],
        "classes": [{"classe_id": "1A", "nome": "1A"}, {"classe_id": "1B", "nome": "1B"}]
    }

@app.post("/api/schedule/{week}/modify-slot")
async def modify_slot(week: str, body: dict):
    """Modify single schedule slot."""
    return {
        "status": "modified",
        "quality_score": 87,
        "quality_level": "B",
        "slots": []
    }

@app.post("/api/schedule/{week}/apply-quick-action")
async def apply_quick_action(week: str, body: dict):
    """Apply quick action deroga."""
    return {
        "status": "applied",
        "quality_score": 84,
        "quality_level": "B",
        "slots": []
    }

@app.post("/api/schedule/{week}/regenerate")
async def regenerate_schedule(week: str):
    """Regenerate schedule from scratch."""
    return {
        "status": "regenerated",
        "quality_score": 88,
        "quality_level": "A",
        "slots": []
    }

@app.post("/api/schedule/{week}/approve")
async def approve_schedule(week: str, body: dict):
    """Approve schedule."""
    return {
        "status": "approved",
        "schedule_id": "sch_latest",
        "stato": "APPROVATO"
    }

@app.get("/api/schedule/{week}/export-pdf")
async def export_pdf(week: str):
    """Export schedule as PDF."""
    return {
        "status": "ok",
        "pdf_url": "/tmp/orario.pdf",
        "message": "PDF export ready (implementation in backend)"
    }

# ============ CHAT ENDPOINTS ============

@app.post("/api/chat/send")
async def chat_send(body: dict):
    """Send chat message with SSE streaming."""
    async def event_generator():
        schedule_id = body.get("schedule_id", "sch_latest")
        message = body.get("message", "")

        # Simulate streaming responses
        yield b"data: " + json.dumps({"type": "thinking", "text": f"Analizzando: {message}"}).encode() + b"\n\n"

        import asyncio
        await asyncio.sleep(1)

        yield b"data: " + json.dumps({"type": "suggestion", "text": f"Ho capito: {message}"}).encode() + b"\n\n"

        await asyncio.sleep(1)

        yield b"data: " + json.dumps({
            "type": "ready",
            "text": "Modifiche applicate",
            "new_score": 87,
            "new_schedule": {
                "schedule_id": schedule_id,
                "quality_score": 87,
                "quality_level": "B",
                "stato": "BOZZA",
                "slots": []
            }
        }).encode() + b"\n\n"

        # Store in history
        if schedule_id not in chat_history:
            chat_history[schedule_id] = []
        chat_history[schedule_id].append({
            "role": "admin",
            "text": message,
            "timestamp": datetime.now().isoformat()
        })
        chat_history[schedule_id].append({
            "role": "ai",
            "text": "Modifiche applicate",
            "timestamp": datetime.now().isoformat()
        })

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/api/chat/history/{schedule_id}")
async def chat_history_get(schedule_id: str):
    """Get chat history for schedule."""
    messages = chat_history.get(schedule_id, [])
    return {"messages": messages}

# ============ HEALTH CHECK ============

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/docs")
async def swagger_ui():
    """Redirect to Swagger UI."""
    return JSONResponse({"message": "API docs at /docs"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
