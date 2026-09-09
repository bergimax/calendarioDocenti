# Frontend Design v1 - Componenti & API Calls

## Architettura Frontend

**Stack:**
- React/Next.js (desktop-first)
- Tailwind CSS
- SSE (Server-Sent Events) per AI chat

**3 Main Pages:**
1. Setup Iniziale (Onboarding)
2. Gestione Disponibilità Docenti (Settimanale)
3. Dashboard Orario (Generazione + Iterazioni)

---

## 1. PAGE: Setup Iniziale

### Descrizione
Admin carica file (Calendario PDF, Docenti CSV, Classi CSV, Materie CSV, Assegnazioni CSV, Accoppiamenti CSV). AI estrae dati, mostra preview, chiede conferma. Admin corregge errori in real-time. Al salvataggio, accesso a "Disponibilità Docenti".

### Layout

```
┌─────────────────────────────────────────┐
│ SETUP INIZIALE ANNO                     │
├─────────────────────────────────────────┤
│                                         │
│ [Carica Calendario PDF]                 │
│ [Carica Docenti CSV]                    │
│ [Carica Classi CSV]                     │
│ [Carica Materie CSV]                    │
│ [Carica Assegnazioni CSV]               │
│ [Carica Accoppiamenti CSV]              │
│                                         │
│ [Procedi alla Validazione]              │
│                                         │
└─────────────────────────────────────────┘
```

### Componenti & API Calls

#### 1.1 Upload Section

**Componente:** `FileUpload`

```tsx
// Props
interface FileUploadProps {
  fileType: 'calendario' | 'docenti' | 'classi' | 'materie' | 'assegnazioni' | 'accoppiamenti';
  onUploadSuccess: (data) => void;
  onUploadError: (error) => void;
}

// API Calls
POST /api/calendar/upload          (se calendario)
POST /api/teachers/upload          (se docenti)
POST /api/classes/upload           (se classi)
POST /api/subjects/upload          (se materie)
POST /api/assignments/upload       (se assegnazioni)
POST /api/class-pairings/upload    (se accoppiamenti)

// Response per tutti
{
  "status": "uploaded",
  "file_id": "uuid",
  "file_type": "calendario",
  "preview": { ... }  // anteprima grezzo
}
```

**Comportamento:**
- Drag-and-drop
- Validazione file (tipo MIME, size)
- Progress bar upload
- Error message se fallisce

---

#### 1.2 Validation & Preview Section

**Componente:** `ValidationPreview`

```tsx
// Props
interface ValidationPreviewProps {
  files: FileUploadResult[];
  onProceed: () => void;
  onEditFile: (fileType) => void;
}

// API Call: Estrae e valida TUTTI i file caricati
POST /api/setup/validate
  Body: {
    file_ids: ["uuid_cal", "uuid_doc", ...]
  }
  
// Response
{
  "status": "validation_complete",
  "results": {
    "calendario": {
      "success": true,
      "preview": {
        "dates_extracted": 180,
        "closures": 25,
        "stages": 3
      },
      "warnings": [],
      "errors": []
    },
    "docenti": {
      "success": true,
      "preview": {
        "count": 15,
        "assunti": 10,
        "contratti": 5
      },
      "warnings": [
        { "docente": "Prof. Rossi", "issue": "email_missing" }
      ],
      "errors": []
    },
    // ... altri file types
  },
  "overall_status": "ready_or_errors",
  "can_proceed": true
}
```

**Comportamento:**
- Mostra preview per file type
- Elenco warning/errors
- [Correggi] button per ogni warning
- [Procedi] se no errors critici

---

#### 1.3 Correction Form (Real-Time)

**Componente:** `CorrectionForm`

```tsx
// Props
interface CorrectionFormProps {
  fileType: string;
  correction: {
    field: string,     // es. "email"
    entity: string,    // es. "Prof. Rossi"
    current_value: string,
    new_value: string
  };
  onSave: () => void;
  onCancel: () => void;
}

// API Call (Real-Time, ogni keystroke)
POST /api/setup/validate-field
  Body: {
    file_type: "docenti",
    entity: "Prof. Rossi",
    field: "email",
    new_value: "massimo@scuola.it"
  }
  
// Response (Real-Time)
{
  "valid": true,
  "message": "Email valida. Docente trovato in lista.",
  "suggestions": []
}

// API Call (Salva correzione)
POST /api/setup/apply-correction
  Body: {
    file_id: "uuid_doc",
    correction: { ... }
  }
  
// Response
{
  "status": "correction_applied",
  "re_validate": true  // trigger ri-validazione
}
```

**Comportamento:**
- Form per campo specifico
- Real-time validation feedback
- [Salva] applica e re-valida tutto
- Mostra nuovi warning (se ce ne sono)

---

#### 1.4 Fallback Manuale (OCR Fallito)

**Componente:** `ManualCalendarInput`

```tsx
// Props
interface ManualCalendarInputProps {
  onAddDate: (date: CalendarEntry) => void;
  onRetryOCR: () => void;
}

interface CalendarEntry {
  data: Date;
  ore_max_giornata: 4 | 5 | 6;
  flag_chiusura: boolean;
  flag_stage_classe_id?: string;
}

// API Call: Aggiungi data manualmente
POST /api/calendar/add-date-manual
  Body: {
    file_id: "uuid_cal",
    date: "2026-09-04",
    ore_max_giornata: 5,
    flag_chiusura: false,
    flag_stage_classe_id: null
  }
  
// Response
{
  "status": "date_added",
  "total_dates_loaded": 46
}

// API Call: Ri-valida calendario dopo aggiunte manuali
POST /api/setup/validate
  Body: { file_ids: ["uuid_cal"] }
  
// Response (stesso di prima)
```

**Comportamento:**
- [+ Aggiungi Data] form
- Input: data, ore_max, tipo
- Dropdown per stage_classe (se applicabile)
- [Continua] quando soddisfatto

---

#### 1.5 Final Confirmation & Save

**Componente:** `FinalConfirmation`

```tsx
// Props
interface FinalConfirmationProps {
  validationResults: ValidationResult;
  onConfirm: () => void;
  onRevise: () => void;
}

// API Call: Salva TUTTO nel DB
POST /api/setup/save
  Body: {
    file_ids: ["uuid_cal", "uuid_doc", ...],
    corrections_applied: [ ... ],
    school_name: "Istituto XYZ",
    school_year: "2026-2027"
  }
  
// Response
{
  "status": "setup_complete",
  "school_id": "sch_123",
  "next_page": "/disponibilita/1"  // redirect
}
```

**Comportamento:**
- Mostra recap finale (docenti, classi, materie, etc)
- [Salva e Inizia] → redirect a Disponibilità
- [Rivedi Dati] → torna a validazione

---

## 2. PAGE: Gestione Disponibilità Docenti

### Descrizione
Admin seleziona settimana, visualizza griglia per docente (ore × giorni), marca disponibilità con toggle. Può copiare da settimana scorsa, salvare per docente, o salvare tutto in blocco.

### Layout

```
┌──────────────────────────────────────────────┐
│ DISPONIBILITÀ DOCENTI - SETTIMANA [date]   │
│ [Indietro] | [Copia Scorsa] | [Genera Ora]  │
├──────────────────────────────────────────────┤
│                                              │
│ Prof. Rossi (Matematica)                    │
│ ┌──────┬────┬────┬────┬────┬────┐          │
│ │ Ora  │Lun │Mar │Mer │Gio │Ven │          │
│ ├──────┼────┼────┼────┼────┼────┤          │
│ │08-09 │ █  │    │ █  │ █  │    │          │
│ │09-10 │ █  │ █  │ █  │ █  │ █  │          │
│ │... 6 rows ...                  │          │
│ └──────┴────┴────┴────┴────┴────┘          │
│ [Select All] [Clear All] [Salva]            │
│                                              │
│ ─────────────────────────────────────────── │
│ Prof. Neri (Inglese)                       │
│ ... (griglia simile)                        │
│                                              │
│ [Scroll per altri docenti...]               │
│                                              │
│ ┌─────────────────────────────────────┐    │
│ │ [← Indietro] [Salva Tutto] [Genera] │    │
│ └─────────────────────────────────────┘    │
│                                              │
└──────────────────────────────────────────────┘
```

### Componenti & API Calls

#### 2.1 Week Selector

**Componente:** `WeekSelector`

```tsx
// Props
interface WeekSelectorProps {
  currentWeek: Date;
  onSelectWeek: (date: Date) => void;
}

// API Call: Recupera lista settimane disponibili
GET /api/availability/weeks
  
// Response
{
  "weeks": [
    { "start": "2026-09-04", "end": "2026-09-08", "week_num": 1 },
    { "start": "2026-09-11", "end": "2026-09-15", "week_num": 2 },
    ...
  ]
}
```

**Comportamento:**
- Dropdown: "Settimana 1 (04-08 Set)"
- Seleziona settimana → carica disponibilità docenti

---

#### 2.2 Teacher Availability Grid

**Componente:** `TeacherAvailabilityGrid`

```tsx
// Props
interface TeacherAvailabilityGridProps {
  teacher_id: string;
  week_start: Date;
  initialData: AvailabilityData;
  onSave: (data) => void;
}

interface AvailabilityData {
  lunedi: AvailabilitySlot[];
  martedi: AvailabilitySlot[];
  // ... altri giorni
}

interface AvailabilitySlot {
  ora_inizio: "08:00";
  ora_fine: "09:00";
  disponibile: boolean;
}

// API Call: Recupera disponibilità docente (settimana specifica)
GET /api/availability/{week_start}/{teacher_id}
  
// Response
{
  "teacher_id": "doc_1",
  "week_start": "2026-09-04",
  "giorni_fasce": {
    "lunedi": [
      { "ora_inizio": "08:00", "ora_fine": "09:00", "disponibile": true },
      { "ora_inizio": "09:00", "ora_fine": "10:00", "disponibile": true },
      { "ora_inizio": "10:00", "ora_fine": "11:00", "disponibile": false },
      // ... fino a 14:00
    ],
    "martedi": [ ... ],
    // ... altri giorni
  }
}

// API Call: Salva disponibilità (singolo docente)
POST /api/availability/{week_start}/{teacher_id}
  Body: {
    giorni_fasce: { ... }
  }
  
// Response
{
  "status": "saved",
  "teacher_id": "doc_1"
}

// API Call: Copia da settimana scorsa
POST /api/availability/{week_start}/{teacher_id}/copy-from/{prev_week}
  
// Response
{
  "status": "copied",
  "giorni_fasce": { ... }
}
```

**Comportamento:**
- Click cella = toggle █/bianco
- [Select All] / [Clear All]
- [Salva] (per docente)
- Scroll verticale tra docenti
- Ogni salvataggio = POST al backend

---

#### 2.3 Copy Previous Week

**Componente:** `CopyPreviousWeek`

```tsx
// Props
interface CopyPreviousWeekProps {
  currentWeek: Date;
  onCopySuccess: () => void;
}

// API Call: Copia TUTTA la disponibilità da settimana scorsa
POST /api/availability/{current_week}/copy-from/{prev_week}
  
// Response
{
  "status": "copied",
  "teachers_copied": 15,
  "reload": true
}

// Trigger reload della pagina con dati settimana scorsa pre-compilati
```

**Comportamento:**
- [Copia Settimana Scorsa] button top
- Carica griglie per tutti i docenti con dati scorsa settimana
- Admin può poi modificare singoli docenti

---

#### 2.4 Save All & Navigation

**Componente:** `AvailabilityFooter`

```tsx
// Props
interface AvailabilityFooterProps {
  week_start: Date;
  unsavedChanges: boolean;
  onBack: () => void;
  onGenerateSchedule: () => void;
}

// API Call: Convalida se tutte disponibilità sono compilate
GET /api/availability/{week_start}/status
  
// Response
{
  "week_complete": true,
  "total_teachers": 15,
  "teachers_with_availability": 15,
  "ready_to_generate": true
}

// (No explicit "Salva Tutto" call - ogni docente salva al click di [Salva])
```

**Comportamento:**
- [← Indietro] → torna homepage/menu
- [Genera Orario] → vai a Dashboard Orario
- Mostra warning se docenti senza disponibilità

---

## 3. PAGE: Dashboard Orario (Generazione + Iterazioni)

### Descrizione
Admin visualizza tabella orario (classi × ore), chat con AI per modifiche, pannello laterale con score e quick actions. Flusso iterativo: genera, modifica, ricalcola, approva, esporta.

### Layout

```
┌─────────────────────────────────────────────────────────────┐
│ ORARIO SETTIMANALE [date] | Week Picker | Logout           │
├──────────────────────┬──────────────────────────────────────┤
│                      │                                      │
│   TABELLA ORARIO     │   PANNELLO LATERALE                  │
│  (Classi × Ore)      │   (Chat + Score + Actions)           │
│                      │                                      │
│  1A│ 2A│ 3A│ ...     │  ┌─ SCORE & STATUS ─────────────┐  │
│  ──┼───┼───┤ ...     │  │ Score: ███░░ 73%              │  │
│  M │ M │ S │         │  │ Conflitti: 2                   │  │
│  █ │   │ █ │         │  │ ✓ Sovrapposizioni: 0          │  │
│  █ │ █ │ █ │ ...     │  │ ⚠ Ore buche: 3                │  │
│    │   │   │         │  └────────────────────────────────┘  │
│                      │                                      │
│  Click cella →       │  ┌─ CHAT SOLVER ─────────────────┐  │
│  Modifica Slot       │  │ [Chat history scrollable]      │  │
│                      │  │                                │  │
│                      │  │ Admin: "Sposta inglese 2A..."  │  │
│                      │  │ [Ricalcola] [Annulla]          │  │
│                      │  ├────────────────────────────────┤  │
│                      │  │ [Textarea input]                │  │
│                      │  │ [Ricalcola Orario]             │  │
│                      │  └────────────────────────────────┘  │
│                      │                                      │
│                      │  ┌─ QUICK ACTIONS ───────────────┐  │
│                      │  │ [Forza 3 Ore Teoria]           │  │
│                      │  │ [Riduci Ore Contratto]         │  │
│                      │  │ [Autorizza Uscita]             │  │
│                      │  └────────────────────────────────┘  │
│                      │                                      │
│                      │  [Approva Settimana]                 │
│                      │  [Esporta PDF]                       │
│                      │  [Genera da Zero]                    │
│                      │                                      │
└──────────────────────┴──────────────────────────────────────┘
```

### Componenti & API Calls

#### 3.1 Generate Schedule Button (Initial)

**Componente:** `GenerateScheduleButton`

```tsx
// Props
interface GenerateScheduleButtonProps {
  week_start: Date;
  onGenerating: () => void;
  onSuccess: (schedule) => void;
  onError: (error) => void;
}

// API Call: Genera orario tramite solver
POST /api/schedule/generate
  Body: {
    week_start: "2026-09-04",
    include_preferences: true
  }
  
// Response (può impiegare 30-60 sec)
{
  "status": "generated",
  "schedule_id": "sch_001",
  "week_start": "2026-09-04",
  "quality_score": 73,
  "quality_level": "B",
  "n_soft_conflicts": 2,
  "schedule": {
    "slots": [
      {
        "classe_id": "cl_1a",
        "docente_id": "doc_1",
        "materia_id": "mat_1",
        "giorno": "lunedi",
        "ora_inizio": "08:00",
        "ora_fine": "09:00"
      },
      // ... molti slot
    ]
  }
}

// Behavor: 
// - Show loading spinner mentre solver gira
// - Cache risultato in state
// - Mostra tabella + score
```

**Comportamento:**
- [Genera Nuovo Orario] button
- Loading state (30-60 sec)
- On success → mostra tabella + score
- On error → mostra messaggio + [Riprova]

---

#### 3.2 Schedule Table Grid

**Componente:** `ScheduleTable`

```tsx
// Props
interface ScheduleTableProps {
  schedule: ScheduleData;
  week_start: Date;
  onSelectSlot: (slot) => void;
  onHighlightTeacher: (teacher_id) => void;
}

interface ScheduleData {
  schedule_id: string;
  slots: SlotLezione[];
  classes: Class[];
  teachers: Teacher[];
}

interface SlotLezione {
  slot_id: string;
  classe_id: string;
  docente_id: string;
  materia_id: string;
  giorno: string;
  ora_inizio: string;
  ora_fine: string;
  accoppiata?: boolean;
  classe_accoppiata_id?: string;
}

// API Call: Recupera orario della settimana (per refresh)
GET /api/schedule/{week_start}
  
// Response
{
  "schedule_id": "sch_001",
  "stato": "BOZZA",
  "quality_score": 73,
  "slots": [ ... ]
}

// Interazioni (no direct API call, ma gestite da componenti child):
// - Click cella → open ModifySlot form
// - Hover cella → tooltip monte ore residuo
// - Click docente name → highlight docente (frontend only)
```

**Comportamento:**
- Rendering dinamico: righe=ore (1-6), colonne=classi
- Colori per materia tipo (blu=teoria, arancio=pratica)
- Celle accoppiate = colspan su 2 colonne
- Click cella → apri form modifica
- Hover → tooltip con ore residue

---

#### 3.3 Modify Slot Form

**Componente:** `ModifySlotPanel`

```tsx
// Props
interface ModifySlotPanelProps {
  slot: SlotLezione;
  week_start: Date;
  onSubmit: () => void;
  onCancel: () => void;
}

// API Call: Modifica singolo slot + ricalcola
POST /api/schedule/{week_start}/modify-slot
  Body: {
    slot_id: "slot_123",
    changes: {
      docente_id: "doc_2",  // optional
      giorno: "mercoledi",   // optional
      ora_inizio: "10:00",   // optional
      ora_fine: "11:00"      // optional
    }
  }
  
// Response
{
  "status": "modified",
  "schedule_id": "sch_001",
  "quality_score": 78,  // nuovo score
  "quality_level": "B",
  "n_soft_conflicts": 1,
  "slots": [ ... ]  // orario aggiornato
}
```

**Comportamento:**
- Form nel pannello laterale
- Dropdown per Docente, Giorno, Ora
- [Salva] applica e ricalcola
- [Annulla] chiude form
- Mostra nuovo score dopo ricalcolo

---

#### 3.4 AI Chat Component

**Componente:** `AIChatPanel`

```tsx
// Props
interface AIChatPanelProps {
  schedule_id: string;
  week_start: Date;
  onScheduleUpdate: (schedule) => void;
}

interface ChatMessage {
  role: "admin" | "ai";
  text: string;
  timestamp: Date;
  actions?: ActionButton[];
}

interface ActionButton {
  label: string;
  action_id: string;
  onClick: () => void;
}

// API Call: Invia messaggio naturale (SSE stream)
POST /api/chat/send
  Body: {
    schedule_id: "sch_001",
    week_start: "2026-09-04",
    message: "Sposta inglese 2A dal martedì al mercoledì"
  }
  
// Response: SSE Stream
// event: message
// data: {"type": "thinking", "text": "Analizzando richiesta..."}
// 
// event: message
// data: {"type": "suggestion", "text": "Propongo di spostare inglese 2A a mercoledì 10:00..."}
// 
// event: message
// data: {"type": "ready", "new_score": "81%", "new_schedule": {...}}

// API Call: Recupera storico chat
GET /api/chat/history/{week_start}
  
// Response
{
  "messages": [
    { "role": "admin", "text": "...", "timestamp": "..." },
    { "role": "ai", "text": "...", "timestamp": "..." }
  ]
}
```

**Comportamento:**
- Chat history scrollabile
- Input textbox per nuovo messaggio
- SSE stream per risposte real-time
- Mostra [Conferma] / [Annulla] buttons per azioni
- Auto-update tabella orario quando AI conferma modifica

---

#### 3.5 Quick Actions

**Componente:** `QuickActionsPanel`

```tsx
// Props
interface QuickActionsPanelProps {
  schedule_id: string;
  week_start: Date;
  conflicts: Conflict[];
  onActionApplied: () => void;
}

interface Conflict {
  conflict_id: string;
  description: string;
  suggested_action: {
    action_type: string;  // "force_hours", "reduce_contract", etc
    label: string;
  }
}

// API Call: Applica quick action (deroga)
POST /api/schedule/{week_start}/apply-quick-action
  Body: {
    action_type: "force_3_hours_theory",
    class_id: "cl_1a",
    parameters: { ... }
  }
  
// Response
{
  "status": "applied",
  "schedule_id": "sch_001",
  "quality_score": 68,
  "quality_level": "C",
  "n_soft_conflicts": 3,
  "slots": [ ... ]  // orario aggiornato
}
```

**Comportamento:**
- Lista di pulsanti dinamici basati su conflitti rilevati
- Click pulsante → applica deroga → ricalcola
- Mostra impatto su score

---

#### 3.6 Quality Score & Status

**Componente:** `QualityScorePanel`

```tsx
// Props
interface QualityScorePanelProps {
  schedule_id: string;
  quality_score: number;
  quality_level: string;  // "A", "B", "C"
  n_soft_conflicts: number;
  conflicts: Conflict[];
}

// API Call: Recupera dettagli score (lo fa già quando genera orario)
GET /api/schedule/{week_start}/quality-score
  
// Response
{
  "quality_score": 73,
  "quality_level": "B",
  "details": {
    "soft_constraints_satisfied": 8,
    "soft_constraints_total": 10,
    "breakdown": {
      "teoria_consecutive": { "satisfied": true, "weight": 15 },
      "pratica_blocks": { "satisfied": false, "weight": 20 },
      // ...
    }
  }
}
```

**Comportamento:**
- Mostra score in progress bar
- Click per expandi dettagli
- Lista conflitti soft irrisolti

---

#### 3.7 Approve & Export

**Componente:** `ApprovalFooter`

```tsx
// Props
interface ApprovalFooterProps {
  schedule_id: string;
  week_start: Date;
  quality_level: string;
  onApproveSuccess: () => void;
  onExportSuccess: (url) => void;
}

// API Call: Approva orario (lock APPROVATO)
POST /api/schedule/{week_start}/approve
  Body: {
    schedule_id: "sch_001"
  }
  
// Response
{
  "status": "approved",
  "schedule_id": "sch_001",
  "stato": "APPROVATO",
  "approved_at": "2026-09-04T14:30:00Z"
}

// API Call: Esporta PDF
GET /api/schedule/{week_start}/export-pdf
  
// Response
{
  "status": "success",
  "pdf_url": "https://..."  // download link
}

// API Call: Rigenerai da zero
POST /api/schedule/{week_start}/regenerate
  Body: {}
  
// Response (stesso di generate, nuovo schedule_id)
```

**Comportamento:**
- [Approva Settimana] → POST approve → lock read-only
- [Esporta PDF] → download tabellone
- [Genera da Zero] → POST regenerate → refresh table

---

## 4. PAGE: Gestione Dati Post-Setup (Bonus)

### Descrizione
Admin può modificare dati in qualsiasi momento (calendario, docenti, materie, assegnazioni, accoppiamenti).

### Menu Principale

**Componente:** `MainMenu`

```
[Gestione Disponibilità] → vai a disponibilità page
[Genera Orario] → vai a dashboard page
[Gestione Dati Scuola]
  ├─ [Calendario]
  ├─ [Docenti]
  ├─ [Classi]
  ├─ [Materie & Assegnazioni]
  └─ [Accoppiamenti]
```

### 4.1 Calendario Management

**Componente:** `CalendarManagement`

```tsx
// API Calls:

GET /api/calendar
  // Response: lista tutte date calendario

POST /api/calendar/add-date
  Body: { data, ore_max_giornata, flag_chiusura, stage_classe_id }
  
PUT /api/calendar/{date_id}
  Body: { ore_max_giornata, flag_chiusura, stage_classe_id }
  
DELETE /api/calendar/{date_id}
```

**Comportamento:**
- [Visualizza] → lista date
- [Aggiungi Date] → form
- [Modifica] → edit form
- [Rimuovi] → confirm delete

---

### 4.2 Docenti Management

**Componente:** `TeachersManagement`

```tsx
// API Calls:

GET /api/teachers
  // Response: lista docenti

POST /api/teachers
  Body: { nome, email, tipo }
  
PUT /api/teachers/{teacher_id}
  Body: { nome, email, tipo }
  
DELETE /api/teachers/{teacher_id}
  Body: { keep_history, reassign_to_teacher, remove_future }
  // Response: conferma rimozione + impatto
```

**Comportamento:**
- [Lista Docenti] → tabella
- [Aggiungi Nuovo] → form
- [Modifica] → edit form
- [Rimuovi] → dialog con opzioni (storico, riassegnazione)

---

### 4.3 Materie & Assegnazioni

**Componente:** `AssignmentsManagement`

```tsx
// API Calls:

GET /api/assignments
  // Response: lista assegnazioni

POST /api/assignments
  Body: { docente_id, classe_id, materia_id, ore_totali }
  
PUT /api/assignments/{assignment_id}
  Body: { ore_totali, docente_id }
  
DELETE /api/assignments/{assignment_id}
```

**Comportamento:**
- [Lista Assegnazioni] → tabella (docente × classe × materia × ore)
- [Modifica Monte Ore] → edit form
- [Riassegna Docente] → dropdown nuovo docente

---

## Flusso Utente Completo

```
1. LOGIN (Admin)
   ↓
2. Prima volta? → SETUP INIZIALE
   - Carica file
   - AI valida e chiede correzioni
   - Salva dati nel DB
   - Redirect a Disponibilità
   ↓
3. DISPONIBILITÀ (Settimanale)
   - Seleziona settimana
   - Marca disponibilità docenti
   - Copia da settimana scorsa (opzionale)
   - Salva
   - [Genera Orario]
   ↓
4. DASHBOARD ORARIO
   - Solver genera orario
   - Visualizza tabella + score
   - Iterazioni:
     a) Click cella → modifica slot → ricalcola
     b) Chat naturale → AI traduce → ricalcola
     c) Quick action → deroga → ricalcola
   - Quando OK → [Approva]
   ↓
5. ORARIO APPROVATO (read-only)
   - [Esporta PDF] → download
   - Prossima settimana → torna a Disponibilità
   ↓
6. GESTIONE DATI SCUOLA (in qualsiasi momento)
   - Modifica calendario, docenti, materie, assegnazioni
   - Aggiungi/rimuovi docenti
   - Ricalcoli monte ore
```

---

## Note Implementative

- **No codice** scritto ancora (questa è documentazione di design)
- Tutte le API calls sono **non implementate**
- SSE richiede connection setup lato backend
- Rate limiting su `/schedule/generate`
- Error handling globale per timeout/infattibilità
- State management: usare Context API o Redux per:
  - Schedule corrente
  - Chat history
  - UI state (selected week, expanded panels, etc)
