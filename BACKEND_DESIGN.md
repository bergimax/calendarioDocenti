# Backend Design v1 - Logica Dettagliata

## Stack Tecnologico

- **Framework:** FastAPI (Python)
- **Database:** PostgreSQL (single-tenant)
- **Solver:** Google OR-Tools (CP-SAT)
- **AI/NLP:** LLM con function calling (Claude API)
- **Async:** FastAPI async handlers
- **Queue (optional):** Celery per solver long-running

---

## Architettura Layers

```
┌──────────────────────────┐
│   FastAPI Routes         │  (app/routes/*.py)
├──────────────────────────┤
│   Service Layer          │  (app/services/*.py)
│  - ScheduleService       │
│  - AvailabilityService   │
│  - SetupService          │
│  - ChatService           │
├──────────────────────────┤
│   Domain/Logic Layer     │  (app/domain/*.py)
│  - Solver                │
│  - Parser                │
│  - Validator             │
├──────────────────────────┤
│   Repository/DAL         │  (app/repositories/*.py)
│  - Database queries      │
├──────────────────────────┤
│   Models & Schemas       │  (app/models/, app/schemas/)
├──────────────────────────┤
│   PostgreSQL Database    │
└──────────────────────────┘
```

---

## 1. Setup Module (Onboarding)

### 1.1 Upload Endpoint: POST `/api/calendar/upload`

**Logica:**
```
1. Ricevi file PDF
2. Valida MIME type (application/pdf)
3. Salva in temp storage (S3 o filesystem)
4. Ritorna file_id + metadati

Input:
  - file (binary)
  
Output:
  - file_id: "uuid_cal_1"
  - status: "uploaded"
  - file_type: "calendario"
  - preview: null (ancora non estratto)
  
Error Handling:
  - File too large → 413
  - Invalid MIME → 400
  - Storage error → 500
```

### 1.2 Validation Endpoint: POST `/api/setup/validate`

**Logica Dettagliata:**

```python
def validate_all_files(file_ids: List[str]):
    """
    Orchestrates validation of ALL uploaded files.
    Returns structured feedback per file type.
    """
    
    results = {}
    
    # 1. CALENDARIO PARSING
    if "calendario" in file_ids:
        pdf_path = get_temp_file("uuid_cal")
        
        try:
            # 1a. OCR extraction (PyPDF + AI-assisted)
            dates_text = extract_text_from_pdf(pdf_path)
            
            # 1b. AI parsing (LLM prompt engineering)
            prompt = f"""
            Extract from this calendar text:
            - All dates (DD/MM/YYYY format)
            - Closure days
            - Stage periods (class, start date, end date)
            
            Calendar text:
            {dates_text}
            
            Return JSON: {{
              "dates": [{{date, ore_max_giornata, flag_chiusura, stage_classe}}],
              "confidence": 0.95,
              "warnings": []
            }}
            """
            
            parsed = call_llm_with_function_calling(prompt)
            # Returns: {"dates": [...], "confidence": 0.95, "warnings": [...]}
            
            # 1c. Validation
            validate_dates_format(parsed["dates"])
            validate_date_ranges(parsed["dates"])
            
            results["calendario"] = {
                "success": True,
                "preview": {
                    "dates_extracted": len(parsed["dates"]),
                    "closures": sum(1 for d in parsed["dates"] if d.flag_chiusura),
                    "stages": count_unique_stage_periods(parsed["dates"])
                },
                "warnings": parse_warnings(parsed["warnings"]),
                "errors": [],
                "parsed_data": parsed  # cache per step successivo
            }
            
        except OCRError as e:
            results["calendario"] = {
                "success": False,
                "preview": null,
                "warnings": [],
                "errors": [{"type": "ocr_failed", "message": str(e)}]
            }
    
    # 2. DOCENTI PARSING (CSV)
    if "docenti" in file_ids:
        csv_path = get_temp_file("uuid_doc")
        
        try:
            docenti_df = pd.read_csv(csv_path)
            
            # Validate columns
            required_cols = ["nome", "email", "tipo"]
            if not all(col in docenti_df.columns for col in required_cols):
                raise ValueError(f"Missing columns: {required_cols}")
            
            # Parse
            docenti = []
            warnings = []
            for idx, row in docenti_df.iterrows():
                docente = {
                    "nome": row["nome"].strip(),
                    "email": row.get("email", "").strip() or None,
                    "tipo": row["tipo"].upper(),  # ASSUNTO | CONTRATTO
                }
                
                # Validate
                if docente["tipo"] not in ["ASSUNTO", "CONTRATTO"]:
                    warnings.append({
                        "row": idx,
                        "issue": f"Invalid tipo: {docente['tipo']}"
                    })
                    continue
                
                if not docente["email"]:
                    warnings.append({
                        "row": idx,
                        "docente": docente["nome"],
                        "issue": "email_missing"
                    })
                
                docenti.append(docente)
            
            results["docenti"] = {
                "success": len(docenti) > 0,
                "preview": {
                    "count": len(docenti),
                    "assunti": sum(1 for d in docenti if d["tipo"] == "ASSUNTO"),
                    "contratti": sum(1 for d in docenti if d["tipo"] == "CONTRATTO")
                },
                "warnings": warnings,
                "errors": [] if len(docenti) > 0 else [{"type": "no_valid_rows"}],
                "parsed_data": docenti
            }
            
        except Exception as e:
            results["docenti"] = {
                "success": False,
                "preview": null,
                "warnings": [],
                "errors": [{"type": "csv_parse_error", "message": str(e)}]
            }
    
    # 3-5. CLASSI, MATERIE, ASSEGNAZIONI, ACCOPPIAMENTI (similar pattern)
    # ... (logic similar to docenti - CSV parsing + validation)
    
    # 6. CROSS-VALIDATION (coherence check)
    cross_errors = validate_data_coherence(results)
    for error in cross_errors:
        # Add to relevant file type
        error_type = error["type"]  # es "docente_not_found_in_classes"
        affected_file = error["file"]  # "assegnazioni"
        results[affected_file]["errors"].append(error)
    
    # 7. Overall status
    overall_status = "ready" if all(r["errors"] == [] for r in results.values()) else "errors"
    can_proceed = all(r["success"] for r in results.values())
    
    return {
        "status": "validation_complete",
        "results": results,
        "overall_status": overall_status,
        "can_proceed": can_proceed
    }
```

**Error Scenarios:**
- OCR fails → suggest manual fallback
- CSV malformed → show row numbers
- Missing docente in assignments → list missing
- Duplicate class names → ask clarification
- Incoherent stage dates → warn

---

### 1.3 Correction Endpoint: POST `/api/setup/validate-field`

**Logica (Real-Time Validation):**

```python
def validate_single_field(file_type: str, entity: str, field: str, new_value: str):
    """
    Real-time validation as admin types corrections.
    Provides immediate feedback.
    """
    
    # 1. Validate field format
    if file_type == "docenti" and field == "email":
        if not is_valid_email(new_value):
            return {
                "valid": False,
                "message": "Email format non valida",
                "suggestions": []
            }
    
    # 2. Check for conflicts/duplicates
    if file_type == "docenti" and field == "nome":
        existing = db.session.query(Docente).filter_by(nome=new_value).first()
        if existing:
            return {
                "valid": False,
                "message": "Docente con questo nome esiste già",
                "suggestions": [existing.nome]
            }
    
    # 3. Cross-reference validation
    if file_type == "assegnazioni" and field == "classe_id":
        classe_exists = db.session.query(Classe).filter_by(id=new_value).first()
        if not classe_exists:
            return {
                "valid": False,
                "message": f"Classe {new_value} non trovata",
                "suggestions": get_similar_class_names(new_value)
            }
    
    # 4. If valid
    return {
        "valid": True,
        "message": "Validato ✓",
        "suggestions": []
    }
```

---

### 1.4 Apply Correction Endpoint: POST `/api/setup/apply-correction`

**Logica:**

```python
def apply_correction(file_id: str, correction: dict):
    """
    Applies single correction to cached parsed data.
    Triggers re-validation of related data.
    """
    
    # 1. Update cached parsed_data
    cached_data = get_cached_parse_result(file_id)
    
    entity = correction["entity"]
    field = correction["field"]
    new_value = correction["new_value"]
    
    # Find and update entity in cached data
    for item in cached_data:
        if item["nome"] == entity:  # or other identifier
            item[field] = new_value
            break
    
    # 2. Re-validate this file type
    validation_result = validate_file_type(file_id, cached_data)
    
    # 3. Check if cross-validation still passes
    all_cached_data = get_all_cached_parse_results()
    cross_errors = validate_data_coherence(all_cached_data)
    
    return {
        "status": "correction_applied",
        "re_validate": True,
        "new_validation": validation_result,
        "cross_errors": cross_errors
    }
```

---

### 1.5 Final Save Endpoint: POST `/api/setup/save`

**Logica (Transazione DB):**

```python
def save_all_data(file_ids: List[str], corrections_applied: List[dict], school_data: dict):
    """
    Saves ALL validated data to PostgreSQL in transaction.
    Creates initial school record with all entities.
    """
    
    try:
        with db.session.begin_nested():  # Transaction
            
            # 1. CREATE SCUOLA
            scuola = Scuola(
                nome=school_data["school_name"],
                anno_formativo=school_data["school_year"],
                data_inizio_anno=school_data["data_inizio"],
                data_fine_anno=school_data["data_fine"]
            )
            db.session.add(scuola)
            db.session.flush()  # Get scuola.id
            
            # 2. INSERT CALENDARIO
            calendario_data = get_cached_parse_result("uuid_cal")
            for entry in calendario_data:
                cal = CalendarioAnnuale(
                    scuola_id=scuola.id,
                    data=entry["data"],
                    ore_max_giornata=entry["ore_max_giornata"],
                    flag_chiusura=entry["flag_chiusura"],
                    flag_stage_classe_id=entry.get("flag_stage_classe_id")
                )
                db.session.add(cal)
            
            # 3. INSERT DOCENTI
            docenti_data = get_cached_parse_result("uuid_doc")
            docente_map = {}  # nome → id per lookups successivi
            for entry in docenti_data:
                docente = Docente(
                    scuola_id=scuola.id,
                    nome=entry["nome"],
                    email=entry["email"],
                    tipo=entry["tipo"],
                    first_time_this_year=True
                )
                db.session.add(docente)
                db.session.flush()
                docente_map[entry["nome"]] = docente.id
            
            # 4. INSERT CLASSI
            classi_data = get_cached_parse_result("uuid_class")
            classe_map = {}
            for entry in classi_data:
                classe = Classe(
                    scuola_id=scuola.id,
                    nome=entry["nome"],
                    n_studenti=entry.get("n_studenti", 0)
                )
                db.session.add(classe)
                db.session.flush()
                classe_map[entry["nome"]] = classe.id
            
            # 5. INSERT MATERIE
            materie_data = get_cached_parse_result("uuid_mat")
            materia_map = {}
            for entry in materie_data:
                materia = Materia(
                    scuola_id=scuola.id,
                    nome=entry["nome"],
                    tipo=entry["tipo"],
                    peso_cognitivo=entry["peso_cognitivo"]
                )
                db.session.add(materia)
                db.session.flush()
                materia_map[entry["nome"]] = materia.id
            
            # 6. INSERT ASSEGNAZIONI
            assegnazioni_data = get_cached_parse_result("uuid_asg")
            for entry in assegnazioni_data:
                docente_id = docente_map[entry["docente_nome"]]
                classe_id = classe_map[entry["classe_nome"]]
                materia_id = materia_map[entry["materia_nome"]]
                
                assegnazione = Assegnazione(
                    scuola_id=scuola.id,
                    docente_id=docente_id,
                    classe_id=classe_id,
                    materia_id=materia_id
                )
                db.session.add(assegnazione)
            
            # 7. INSERT MONTE_ORE_ANNUALE
            for entry in assegnazioni_data:
                docente_id = docente_map[entry["docente_nome"]]
                classe_id = classe_map[entry["classe_nome"]]
                materia_id = materia_map[entry["materia_nome"]]
                
                monte_ore = MonteOreAnnuale(
                    scuola_id=scuola.id,
                    classe_id=classe_id,
                    materia_id=materia_id,
                    docente_id=docente_id,
                    ore_totali=entry["ore_anno"],
                    ore_erogate=0
                )
                db.session.add(monte_ore)
            
            # 8. INSERT CLASSI_ACCOPPIATE
            accoppiamenti_data = get_cached_parse_result("uuid_acc")
            for entry in accoppiamenti_data:
                classe_a_id = classe_map[entry["classe_a"]]
                classe_b_id = classe_map[entry["classe_b"]]
                materia_id = materia_map[entry["materia_nome"]]
                
                accoppiamento = ClasseAccoppiata(
                    scuola_id=scuola.id,
                    classe_a_id=classe_a_id,
                    classe_b_id=classe_b_id,
                    materia_id=materia_id
                )
                db.session.add(accoppiamento)
            
            db.session.commit()
            
            # 9. Cleanup cache
            clear_temp_files(file_ids)
            
            return {
                "status": "setup_complete",
                "school_id": scuola.id,
                "next_page": f"/disponibilita/1"
            }
    
    except Exception as e:
        db.session.rollback()
        logger.error(f"Setup save failed: {e}")
        return {
            "status": "error",
            "message": "Errore nel salvataggio dati",
            "error": str(e)
        }
```

---

## 2. Availability Module (Settimanale)

### 2.1 Get Availability: GET `/api/availability/{week_start}/{teacher_id}`

**Logica:**

```python
def get_availability(week_start: date, teacher_id: str):
    """
    Retrieves availability grid for teacher in specific week.
    If no record exists, returns default (8-14) or previous week if first_time=False.
    """
    
    # 1. Query DB
    availability = db.session.query(DisponibilitaSettimanale).filter_by(
        docente_id=teacher_id,
        settimana_inizio=week_start
    ).first()
    
    if availability:
        return {
            "teacher_id": teacher_id,
            "week_start": week_start,
            "giorni_fasce": availability.giorni_fasce  # JSONB
        }
    
    # 2. If no record: check docente.first_time_this_year
    docente = db.session.query(Docente).filter_by(id=teacher_id).first()
    
    if docente.first_time_this_year:
        # New teacher: return empty grid (default 8-14 all days)
        default_grid = {
            "lunedi": generate_hour_slots(8, 14),      # [8-9, 9-10, ..., 13-14]
            "martedi": generate_hour_slots(8, 14),
            # ... etc
        }
        return {
            "teacher_id": teacher_id,
            "week_start": week_start,
            "giorni_fasce": default_grid,
            "is_default": True
        }
    
    else:
        # Recurring teacher: inherit from previous week
        prev_week_start = week_start - timedelta(days=7)
        prev_availability = db.session.query(DisponibilitaSettimanale).filter_by(
            docente_id=teacher_id,
            settimana_inizio=prev_week_start
        ).first()
        
        if prev_availability:
            return {
                "teacher_id": teacher_id,
                "week_start": week_start,
                "giorni_fasce": prev_availability.giorni_fasce,
                "is_inherited": True
            }
        else:
            # Fallback to default
            return default_grid_response()

def generate_hour_slots(start_hour: int, end_hour: int) -> List[dict]:
    """Helper: generates [{ora_inizio, ora_fine, disponibile}] for day."""
    slots = []
    for h in range(start_hour, end_hour):
        slots.append({
            "ora_inizio": f"{h:02d}:00",
            "ora_fine": f"{h+1:02d}:00",
            "disponibile": True  # default available
        })
    return slots
```

### 2.2 Save Availability: POST `/api/availability/{week_start}/{teacher_id}`

**Logica:**

```python
def save_availability(week_start: date, teacher_id: str, giorni_fasce: dict):
    """
    Saves availability for teacher in week.
    Creates new record or updates existing.
    """
    
    # 1. Validate input
    if not validate_giorni_fasce_format(giorni_fasce):
        raise ValueError("Invalid giorni_fasce format")
    
    # 2. Upsert availability
    availability = db.session.query(DisponibilitaSettimanale).filter_by(
        docente_id=teacher_id,
        settimana_inizio=week_start
    ).first()
    
    if availability:
        # Update existing
        availability.giorni_fasce = giorni_fasce
        availability.updated_at = datetime.now()
    else:
        # Create new
        availability = DisponibilitaSettimanale(
            scuola_id=get_current_school_id(),
            docente_id=teacher_id,
            settimana_inizio=week_start,
            giorni_fasce=giorni_fasce,
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        db.session.add(availability)
    
    db.session.commit()
    
    # 3. Mark teacher as "not first_time" anymore
    docente = db.session.query(Docente).filter_by(id=teacher_id).first()
    if docente.first_time_this_year:
        docente.first_time_this_year = False
        db.session.commit()
    
    return {
        "status": "saved",
        "teacher_id": teacher_id,
        "week_start": week_start
    }
```

### 2.3 Copy Previous Week: POST `/api/availability/{week_start}/copy-from/{prev_week}`

**Logica:**

```python
def copy_availability_from_previous_week(current_week: date, prev_week: date):
    """
    Copies ALL teachers' availability from prev_week to current_week.
    """
    
    # 1. Get all teachers in school
    school_id = get_current_school_id()
    teachers = db.session.query(Docente).filter_by(
        scuola_id=school_id,
        active=True
    ).all()
    
    # 2. For each teacher, copy availability
    copied_count = 0
    for teacher in teachers:
        prev_availability = db.session.query(DisponibilitaSettimanale).filter_by(
            docente_id=teacher.id,
            settimana_inizio=prev_week
        ).first()
        
        if prev_availability:
            # Copy to current week
            new_availability = DisponibilitaSettimanale(
                scuola_id=school_id,
                docente_id=teacher.id,
                settimana_inizio=current_week,
                giorni_fasce=prev_availability.giorni_fasce,
                created_at=datetime.now()
            )
            db.session.add(new_availability)
            copied_count += 1
    
    db.session.commit()
    
    return {
        "status": "copied",
        "teachers_copied": copied_count,
        "from_week": prev_week,
        "to_week": current_week
    }
```

---

## 3. Schedule Generation Module (Solver)

### 3.1 Generate Schedule: POST `/api/schedule/generate`

**Logica Orchestration:**

```python
async def generate_schedule(week_start: date):
    """
    Orchestrates entire schedule generation:
    1. Fetch all constraints (hard + soft)
    2. Call solver
    3. Handle result (optimal, partial, infeasible)
    4. Save to DB
    """
    
    try:
        # 1. FETCH DATA FROM DB
        school_id = get_current_school_id()
        
        classes = db.query(Classe).filter_by(scuola_id=school_id).all()
        teachers = db.query(Docente).filter_by(scuola_id=school_id, active=True).all()
        subjects = db.query(Materia).filter_by(scuola_id=school_id).all()
        assignments = db.query(Assegnazione).filter_by(scuola_id=school_id).all()
        calendar = db.query(CalendarioAnnuale).filter(
            CalendarioAnnuale.scuola_id == school_id,
            CalendarioAnnuale.data >= week_start,
            CalendarioAnnuale.data < week_start + timedelta(days=7)
        ).all()
        paired_classes = db.query(ClasseAccoppiata).filter_by(scuola_id=school_id).all()
        availability = db.query(DisponibilitaSettimanale).filter_by(
            scuola_id=school_id,
            settimana_inizio=week_start
        ).all()
        monte_ore = db.query(MonteOreAnnuale).filter_by(scuola_id=school_id).all()
        
        # 2. BUILD SOLVER PROBLEM
        from ortools.sat.python import cp_model
        
        model = cp_model.CpModel()
        
        # Decision variables: x[classe][docente][materia][day][hour]
        x = {}
        for clase in classes:
            for teacher in teachers:
                for subject in subjects:
                    for day in range(5):  # LUN-VEN
                        for hour in range(6):  # 08-14
                            x[clase.id, teacher.id, subject.id, day, hour] = model.NewBoolVar(
                                f"x_{clase.id}_{teacher.id}_{subject.id}_{day}_{hour}"
                            )
        
        # 3. ADD HARD CONSTRAINTS
        
        # Hard 1: No teacher double-booking
        for teacher in teachers:
            for day in range(5):
                for hour in range(6):
                    # Sum over all class/subject combinations ≤ 1
                    overlapping_slots = [
                        x[c.id, teacher.id, s.id, day, hour]
                        for c in classes for s in subjects
                    ]
                    model.Add(sum(overlapping_slots) <= 1)
        
        # Hard 2: Day capacity constraint
        for clase in classes:
            for day in range(5):
                day_date = week_start + timedelta(days=day)
                max_hours = get_max_hours_for_date(day_date, calendar)
                
                hours_in_day = [
                    x[clase.id, teacher.id, subject.id, day, hour]
                    for teacher in teachers for subject in subjects for hour in range(6)
                ]
                model.Add(sum(hours_in_day) <= max_hours)
        
        # Hard 3: Paired classes must have same hour/teacher
        for pair in paired_classes:
            for teacher in teachers:
                for subject in subjects:
                    for day in range(5):
                        for hour in range(6):
                            # If classe_a assigned, clase_b must be too
                            if (pair.clase_a_id, teacher.id, pair.subject_id, day, hour) in x:
                                x_a = x[pair.clase_a_id, teacher.id, pair.subject_id, day, hour]
                                x_b = x[pair.clase_b_id, teacher.id, pair.subject_id, day, hour]
                                model.Add(x_a == x_b)
        
        # Hard 4: Teacher availability (only ASSUNTO has fixed 8-14)
        for teacher in teachers:
            if teacher.tipo == "ASSUNTO":
                # Only can teach 08:00-14:00 (hours 0-5)
                pass  # Already limited by x variables
            else:
                # CONTRATTO: respect availability grid
                availability_rec = next(
                    (a for a in availability if a.docente_id == teacher.id),
                    None
                )
                if availability_rec:
                    for day_name in ["lunedi", "martedi", "mercoledi", "giovedi", "venerdi"]:
                        day_idx = day_name_to_index(day_name)
                        day_slots = availability_rec.giorni_fasce.get(day_name, [])
                        
                        for slot in day_slots:
                            if not slot["disponibile"]:
                                hour = time_to_hour_index(slot["ora_inizio"])
                                unavailable_assignments = [
                                    x[c.id, teacher.id, s.id, day_idx, hour]
                                    for c in classes for s in subjects
                                ]
                                model.Add(sum(unavailable_assignments) == 0)
        
        # Hard 5: Exclude stage classes
        for clase in classes:
            calendar_rec = next(
                (c for c in calendar if c.flag_stage_classe_id == clase.id),
                None
            )
            if calendar_rec:
                day_idx = (calendar_rec.data - week_start).days
                if 0 <= day_idx < 5:
                    for teacher in teachers:
                        for subject in subjects:
                            for hour in range(6):
                                if (clase.id, teacher.id, subject.id, day_idx, hour) in x:
                                    model.Add(x[clase.id, teacher.id, subject.id, day_idx, hour] == 0)
        
        # 4. ADD SOFT CONSTRAINTS (objective function)
        soft_penalties = []
        
        # Soft 1: Max 2 consecutive hours theory
        for clase in classes:
            for teacher in teachers:
                for day in range(5):
                    theory_subject_ids = [s.id for s in subjects if s.tipo == "TEORIA"]
                    for hour in range(4):  # up to hour 4 (can't have 5,6 consecutive)
                        consecutive_theory = [
                            x[clase.id, teacher.id, s_id, day, hour]
                            for s_id in theory_subject_ids
                        ] + [
                            x[clase.id, teacher.id, s_id, day, hour + 1]
                            for s_id in theory_subject_ids
                        ] + [
                            x[clase.id, teacher.id, s_id, day, hour + 2]
                            for s_id in theory_subject_ids
                        ]
                        # Penalize if 3+ consecutive theory hours
                        excess = model.NewIntVar(0, 3, f"excess_theory_{clase.id}_{day}_{hour}")
                        model.Add(excess >= sum(consecutive_theory) - 2)
                        soft_penalties.append((excess, 10))  # weight 10
        
        # Soft 2: Pratica blocks (3-6 hours)
        # ... (similar pattern)
        
        # Soft 3: Cognitive load balance
        # ... (similar pattern)
        
        # Soft 4: Reduce contractor gaps (holes)
        for teacher in teachers:
            if teacher.tipo == "CONTRATTO":
                for day in range(5):
                    hours_assigned = [
                        x[c.id, teacher.id, s.id, day, h]
                        for c in classes for s in subjects for h in range(6)
                    ]
                    # Count gaps (0 hours in middle of day)
                    # Penalize high gap count
        
        # 5. SET OBJECTIVE
        model.Minimize(sum(penalty * weight for penalty, weight in soft_penalties))
        
        # 6. CALL SOLVER
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = 60  # 60 sec timeout
        status = solver.Solve(model)
        
        # 7. HANDLE RESULT
        if status == cp_model.OPTIMAL or status == cp_model.FEASIBLE:
            # Extract solution
            slots = []
            for x_var, assignment in model.AssignmentIterator(solver):
                if assignment == 1:
                    # Parse variable name to get clase, teacher, subject, day, hour
                    clase_id, teacher_id, subject_id, day, hour = parse_var_name(str(x_var))
                    
                    slots.append({
                        "classe_id": clase_id,
                        "docente_id": teacher_id,
                        "materia_id": subject_id,
                        "giorno": index_to_day_name(day),
                        "ora_inizio": hour,
                        "ora_fine": hour + 1,
                        "accoppiata": check_if_paired(clase_id, paired_classes)
                    })
            
            quality_score = calculate_quality_score(slots, model, soft_penalties, solver)
            quality_level = "A" if quality_score > 95 else "B" if quality_score > 80 else "C"
            
            # 8. SAVE TO DB
            orario = OrarioSettimanale(
                scuola_id=school_id,
                settimana_inizio=week_start,
                stato="BOZZA",
                quality_score=quality_score,
                quality_level=quality_level,
                n_conflitti_soft=count_soft_conflicts(slots)
            )
            db.session.add(orario)
            db.session.flush()
            
            for slot_data in slots:
                slot = SlotLezione(
                    orario_settimanale_id=orario.id,
                    classe_id=slot_data["classe_id"],
                    docente_id=slot_data["docente_id"],
                    materia_id=slot_data["materia_id"],
                    giorno=slot_data["giorno"],
                    ora_inizio=slot_data["ora_inizio"],
                    ora_fine=slot_data["ora_fine"],
                    accoppiata=slot_data["accoppiata"]
                )
                db.session.add(slot)
            
            db.session.commit()
            
            return {
                "status": "generated",
                "schedule_id": orario.id,
                "quality_score": quality_score,
                "quality_level": quality_level,
                "n_soft_conflicts": orario.n_conflitti_soft,
                "slots": slots
            }
        
        elif status == cp_model.INFEASIBLE:
            # Identify conflicting constraints
            conflicting = identify_infeasible_constraints(model)
            return {
                "status": "infeasible",
                "message": "Orario impossibile con vincoli attuali",
                "conflicting_constraints": conflicting,
                "suggested_deroghe": suggest_deroghe(conflicting)
            }
        
        else:  # UNKNOWN
            return {
                "status": "timeout",
                "message": "Solver non ha convergito in 60 secondi",
                "partial_solution": None  # Could return partial if available
            }
    
    except Exception as e:
        logger.error(f"Schedule generation failed: {e}")
        return {
            "status": "error",
            "message": str(e)
        }
```

---

## 4. Chat & AI Module

### 4.1 Send Chat Message: POST `/api/chat/send` (SSE Stream)

**Logica Dettagliata:**

```python
async def send_chat_message(schedule_id: str, week_start: date, message: str):
    """
    Processes admin message in natural language.
    Returns SSE stream with real-time responses.
    """
    
    # 1. NLP PARSING (LLM Function Calling)
    system_prompt = """
    You are a schedule optimization assistant.
    User is an admin managing school schedules.
    
    Parse admin requests into structured JSON.
    Supported intents:
    - "sposta_lezione": Move lesson (materia, classe, from_day, to_day)
    - "riduci_carico": Reduce teacher load (docente, max_ore)
    - "esclusione_giorno": Exclude day (docente, giorno)
    - "vincolo_soft": Add soft constraint (tipo, parametri)
    - "preferenza": Add preference (materia/docente, fascia_oraria)
    
    Return JSON: {
      "intent": "...",
      "parameters": {...},
      "confidence": 0.9,
      "clarifications_needed": []
    }
    """
    
    yield f"data: {json.dumps({'type': 'thinking', 'text': 'Analizzando richiesta...'})}\\n\\n"
    
    try:
        # Call LLM with function calling
        response = call_llm_with_functions(
            system_prompt=system_prompt,
            user_message=message,
            functions=[
                {"name": "parse_intent", "parameters": {...}}
            ]
        )
        
        intent_json = json.loads(response)
        
        # 2. VALIDATION
        yield f"data: {json.dumps({'type': 'thinking', 'text': 'Validando richiesta...'})}\\n\\n"
        
        # Validate parsed intent against current schedule
        validation_errors = validate_intent(intent_json, schedule_id, week_start)
        
        if validation_errors:
            yield f"data: {json.dumps({
                'type': 'clarification',
                'text': f"Puoi chiarire: {'; '.join(validation_errors)}?"
            })}\\n\\n"
            return
        
        # 3. TRANSLATE TO CONSTRAINTS
        yield f"data: {json.dumps({'type': 'thinking', 'text': 'Traducendo a vincoli...'})}\\n\\n"
        
        temp_constraints = translate_intent_to_constraints(intent_json)
        # Returns: ["x[2A][*][Inglese][MARTEDI][*] = 0", ...]
        
        # 4. CALL SOLVER (Warm Start)
        yield f"data: {json.dumps({'type': 'thinking', 'text': 'Ricalcolando orario...'})}\\n\\n"
        
        current_schedule = db.query(OrarioSettimanale).filter_by(id=schedule_id).first()
        
        result = solve_with_temp_constraints(
            schedule_id=schedule_id,
            temp_constraints=temp_constraints,
            warm_start=True  # Start from current solution
        )
        
        # 5. FORMAT RESPONSE
        if result["status"] == "solved_better":
            yield f"data: {json.dumps({
                'type': 'suggestion',
                'text': f"Fatto! {intent_json['parameters']['materia']} 2A ora {result['new_day']} {result['new_hour']}:00.",
                'new_score': result['quality_score']
            })}\\n\\n"
            
            # Update DB
            update_schedule_from_solver(schedule_id, result)
            
            yield f"data: {json.dumps({
                'type': 'ready',
                'new_score': result['quality_score'],
                'new_schedule': result['slots']
            })}\\n\\n"
        
        elif result["status"] == "solved_difficult":
            conflicts = result["conflicts"]
            yield f"data: {json.dumps({
                'type': 'warning',
                'text': f"Possibile, ma {len(conflicts)} conflitti: {'; '.join(conflicts)}. Vuoi procedere?",
                'conflicts': conflicts
            })}\\n\\n"
        
        elif result["status"] == "infeasible":
            alternatives = result["alternatives"]
            yield f"data: {json.dumps({
                'type': 'error',
                'text': "Non posso: vincolo impossibile.",
                'alternatives': alternatives
            })}\\n\\n"
    
    except Exception as e:
        logger.error(f"Chat error: {e}")
        yield f"data: {json.dumps({'type': 'error', 'text': f'Errore: {str(e)}'})}\\n\\n"

def translate_intent_to_constraints(intent: dict) -> List[str]:
    """
    Translates parsed intent to mathematical constraints.
    """
    constraints = []
    
    if intent["intent"] == "sposta_lezione":
        materia = intent["parameters"]["materia"]
        classe = intent["parameters"]["classe"]
        from_day = intent["parameters"]["from_day"]
        to_day = intent["parameters"]["to_day"]
        
        # Constraint 1: Remove from old day
        constraints.append(f"x[{classe}][*][{materia}][{from_day}][*] = 0")
        
        # Constraint 2: Add to new day (at least 1 hour)
        constraints.append(f"x[{classe}][*][{materia}][{to_day}][*] >= 1")
    
    elif intent["intent"] == "riduci_carico":
        docente = intent["parameters"]["docente"]
        max_ore = intent["parameters"]["max_ore"]
        
        # Constraint: total hours ≤ max_ore
        constraints.append(f"sum_hours[{docente}] <= {max_ore}")
    
    return constraints
```

---

## 5. Approval & Export Module

### 5.1 Approve Schedule: POST `/api/schedule/{week_start}/approve`

**Logica:**

```python
def approve_schedule(week_start: date):
    """
    Approves schedule (changes state from BOZZA to APPROVATO).
    Locks it from further modifications.
    Triggers any necessary actions (logging, notifications).
    """
    
    orario = db.query(OrarioSettimanale).filter_by(
        scuola_id=get_current_school_id(),
        settimana_inizio=week_start
    ).first()
    
    if not orario:
        raise ValueError("Schedule not found")
    
    if orario.stato == "APPROVATO":
        return {"status": "already_approved"}
    
    # Update monte ore (ore_erogate)
    slots = db.query(SlotLezione).filter_by(orario_settimanale_id=orario.id).all()
    for slot in slots:
        monte = db.query(MonteOreAnnuale).filter_by(
            classe_id=slot.classe_id,
            materia_id=slot.materia_id,
            docente_id=slot.docente_id
        ).first()
        
        if monte:
            ore_this_slot = 1  # 1 hour
            if slot.accoppiata:
                ore_this_slot = 1  # Still counts as 1 even for paired
            
            monte.ore_erogate += ore_this_slot
    
    # Approve
    orario.stato = "APPROVATO"
    orario.approved_at = datetime.now()
    
    # Audit log
    audit_log = AuditLog(
        scuola_id=get_current_school_id(),
        orario_settimanale_id=orario.id,
        azione="APPROVE",
        admin_id=get_current_admin_id(),
        dettagli={"approved_by": get_current_admin_id()}
    )
    db.session.add(audit_log)
    db.session.commit()
    
    return {
        "status": "approved",
        "schedule_id": orario.id,
        "stato": "APPROVATO",
        "approved_at": orario.approved_at
    }
```

### 5.2 Export PDF: GET `/api/schedule/{week_start}/export-pdf`

**Logica:**

```python
def export_schedule_to_pdf(week_start: date):
    """
    Generates PDF tabellone from approved schedule.
    Uses WeasyPrint to render HTML template.
    """
    
    orario = db.query(OrarioSettimanale).filter_by(
        scuola_id=get_current_school_id(),
        settimana_inizio=week_start
    ).first()
    
    slots = db.query(SlotLezione).filter_by(orario_settimanale_id=orario.id).all()
    
    # 1. Build HTML table
    html_content = build_schedule_html_table(slots, week_start)
    
    # 2. Render with WeasyPrint
    from weasyprint import HTML, CSS
    
    pdf_bytes = HTML(string=html_content).write_pdf(
        stylesheets=[CSS(string=get_schedule_css_styles())]
    )
    
    # 3. Save to S3 / storage
    filename = f"orario_{week_start}.pdf"
    storage_url = upload_to_storage(pdf_bytes, filename)
    
    return {
        "status": "generated",
        "pdf_url": storage_url,
        "filename": filename
    }

def build_schedule_html_table(slots: List[SlotLezione], week_start: date) -> str:
    """
    Generates HTML table representation of schedule.
    """
    
    html = """
    <html>
      <head>
        <title>Orario Scolastico</title>
        <style>
          body { font-family: Arial, sans-serif; }
          table { border-collapse: collapse; width: 100%; }
          th, td { border: 1px solid black; padding: 8px; text-align: center; }
          th { background-color: #f0f0f0; font-weight: bold; }
        </style>
      </head>
      <body>
        <h1>Orario Settimanale - {{week_start}} a {{week_end}}</h1>
        <table>
          <thead>
            <tr>
              <th>Ora</th>
              <th>Lunedì</th>
              <th>Martedì</th>
              <th>Mercoledì</th>
              <th>Giovedì</th>
              <th>Venerdì</th>
            </tr>
          </thead>
          <tbody>
    """
    
    # Group slots by hour
    for hour in range(8, 14):
        html += f"<tr><td>{hour}:00-{hour+1}:00</td>"
        
        for day_idx in range(5):
            day_name = index_to_day_name(day_idx)
            
            # Find slots for this hour/day
            hour_slots = [s for s in slots if s.giorno == day_name and s.ora_inizio == hour]
            
            if hour_slots:
                cell_content = "<br/>".join([
                    f"{slot.materia.nome}<br/>({slot.docente.nome})"
                    for slot in hour_slots
                ])
                html += f"<td>{cell_content}</td>"
            else:
                html += "<td></td>"
        
        html += "</tr>"
    
    html += """
          </tbody>
        </table>
      </body>
    </html>
    """
    
    return html
```

---

## 6. Error Handling & Logging

### Global Error Handler

```python
@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """
    Catches all unhandled exceptions.
    Logs to database + external service.
    Returns standardized error response.
    """
    
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    error_id = str(uuid.uuid4())
    
    # Save to DB for audit
    error_log = ErrorLog(
        error_id=error_id,
        message=str(exc),
        traceback=traceback.format_exc(),
        endpoint=request.url.path,
        method=request.method,
        timestamp=datetime.now()
    )
    db.session.add(error_log)
    db.session.commit()
    
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "message": "Server error. Contact administrator.",
            "error_id": error_id
        }
    )
```

---

## 7. Database Query Patterns

### Efficient Queries

```python
# Query 1: Get full schedule with all relationships
schedule = db.query(OrarioSettimanale).options(
    joinedload(OrarioSettimanale.slots).joinedload(SlotLezione.docente),
    joinedload(OrarioSettimanale.slots).joinedload(SlotLezione.materia),
    joinedload(OrarioSettimanale.slots).joinedload(SlotLezione.classe)
).filter_by(id=schedule_id).first()

# Query 2: Get teacher workload for week
teacher_hours = db.query(
    func.sum(SlotLezione.ora_fine - SlotLezione.ora_inizio)
).join(OrarioSettimanale).filter(
    SlotLezione.docente_id == teacher_id,
    OrarioSettimanale.settimana_inizio == week_start
).scalar()

# Query 3: Check monte ore progress
monte_ore_status = db.query(
    MonteOreAnnuale.ore_totali,
    MonteOreAnnuale.ore_erogate,
    (MonteOreAnnuale.ore_totali - MonteOreAnnuale.ore_erogate).label("residue")
).filter_by(
    classe_id=class_id,
    materia_id=subject_id
).all()
```

---

## 8. Performance Considerations

**Caching Strategy:**
```
- Cache teacher availability per week (Redis 24h TTL)
- Cache calendar dates for year (Redis 7d TTL)
- Cache solver results (in-memory until next generate)
- Invalidate caches on any data modification
```

**Async Patterns:**
```
- Use `asyncio.gather()` for parallel availability fetches
- Stream SSE responses from chat to avoid blocking
- Long-running solver in background worker (Celery optional)
```

**Database Optimization:**
```
- Index on (scuola_id, settimana_inizio) for schedule lookups
- Index on (docente_id, settimana_inizio) for availability
- Use JSONB indexing for giorni_fasce searches
- Batch inserts for slot creation (100 at a time)
```

