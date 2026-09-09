# Frontend Implementation Checklist (Phase 3)

**Estimated Effort:** 20-30 hours
**Backend Status:** 100% ready ✅

---

## Page 1: Setup Page (~8-10 hours)

### Features
- [ ] File upload widget (CSV + drag-drop)
  - [ ] Accept: calendario.csv, docenti.csv, classi.csv, materie.csv, assegnazioni.csv, accoppiamenti.csv
  - [ ] Validate file types (must be CSV)
  - [ ] Show upload progress

- [ ] Validation display
  - [ ] POST /setup/validate (batch parse all files)
  - [ ] Show validation results (errors/warnings)
  - [ ] Display entity preview tables (docenti, classi, materie, etc)

- [ ] Field correction UI
  - [ ] Click on error cell → inline edit
  - [ ] POST /setup/validate-field (real-time validation)
  - [ ] Update preview table with correction
  - [ ] Show validation status per field

- [ ] Final save flow
  - [ ] Input: school name, school year, data_inizio, data_fine
  - [ ] POST /setup/save (transactional)
  - [ ] Success → redirect to Disponibilità page
  - [ ] Error → show error message + retry

### API Calls
```
POST   /calendar/upload                    (upload file)
POST   /setup/validate                     (validate all CSV)
POST   /setup/validate-field               (real-time field fix)
POST   /setup/save                         (finalize setup)
```

---

## Page 2: Disponibilità (Availability) (~6-8 hours)

### Features
- [ ] Teacher grid (interactive availability matrix)
  - [ ] Rows: Teachers (filtered by role: ASSUNTO/CONTRATTO)
  - [ ] Columns: Days (lunedì-venerdì) × Hours (8:00-14:00, 6 slots)
  - [ ] Cells: Clickable toggle (available=filled/unavailable=empty)
  - [ ] Show current availability state

- [ ] Time slot display
  - [ ] Hours shown: 08:00-09:00, 09:00-10:00, ..., 13:00-14:00
  - [ ] Days: lunedì, martedì, mercoledì, giovedì, venerdì

- [ ] Save functionality
  - [ ] On change, POST /availability/{teacher_id} (giorni_fasce format)
  - [ ] Show save status (spinning loader, checkmark, error)
  - [ ] Automatically save without explicit button

- [ ] Copy week feature
  - [ ] Button: "Copy this week to next week"
  - [ ] Confirmation dialog
  - [ ] POST /availability/{teacher_id}/copy-week
  - [ ] Reload grid after copy

- [ ] Status indicators
  - [ ] Show % completion per teacher
  - [ ] Mark teachers as "completed" if all filled
  - [ ] Show "First time setup" vs "Editing existing"

### API Calls
```
GET    /availability/{teacher_id}/week    (load grid)
POST   /availability/{teacher_id}         (save grid)
POST   /availability/{teacher_id}/copy-week (copy to next week)
```

---

## Page 3: Dashboard (Schedule) (~8-12 hours)

### Sections

#### A. Schedule Generation (~3-4 hours)
- [ ] Generate button + timeout UI
  - [ ] Button: "Genera Orario"
  - [ ] On click: POST /schedule/generate
  - [ ] Show spinner with "Solving..." message
  - [ ] Timeout handling (60s limit)

- [ ] Result display
  - [ ] If OPTIMAL/FEASIBLE:
    - [ ] Show quality score (A/B/C + %)
    - [ ] Show "Approved" button
    - [ ] Show "Export PDF" button
    - [ ] Go to section B (schedule table)
  - [ ] If INFEASIBLE:
    - [ ] Show conflicting constraints
    - [ ] Show suggested deroghe (suggestions)
    - [ ] Show "Modify setup" button (go back to setup)
  - [ ] If TIMEOUT:
    - [ ] Show "Try again" button
    - [ ] Show "Use previous schedule" link

#### B. Schedule Table (~3-4 hours)
- [ ] Weekly tabellone (schedule grid)
  - [ ] Rows: Classes + Subjects
  - [ ] Columns: Days (lunedì-venerdì) × Hours (08:00-14:00)
  - [ ] Cells: Show docente, materia, classe_accoppiata (if any)
  - [ ] Color-code: TEORIA=blue, PRATICA=green, STAGE=gray

- [ ] Interactive modifications (warm-start)
  - [ ] Click slot → show modify options
  - [ ] "Move to another slot" dropdown
  - [ ] POST /schedule/{week}/modify-slot
  - [ ] Show updated quality score after modify

- [ ] Conflict indicators
  - [ ] Highlight invalid slots (red border)
  - [ ] Show conflict reason on hover

#### C. Chat Widget (~2-3 hours)
- [ ] Chat panel (right sidebar)
  - [ ] Input field: "Chiedi modifiche..."
  - [ ] Message history (scrollable)
  - [ ] Show thinking → clarification → suggestion → ready flow

- [ ] SSE streaming
  - [ ] POST /chat/send (streaming response)
  - [ ] Display events as they arrive
  - [ ] Show "thinking..." while waiting
  - [ ] Auto-scroll to latest message

- [ ] Chat responses
  - [ ] Support intent: "Sposta inglese 2A da lunedì a martedì"
  - [ ] Support: "Riduci ore Prof. Neri a max 4/settimana"
  - [ ] Support: "Prof. Rossi non lunedì"
  - [ ] Auto-apply modification + recalc (warm-start)
  - [ ] Show new quality score

#### D. Schedule Actions (~2 hours)
- [ ] Approve button
  - [ ] Button: "Approva Orario"
  - [ ] Confirmation dialog: "Sei sicuro? Non potrai modificare dopo."
  - [ ] POST /schedule/{week}/approve
  - [ ] Update UI to show APPROVATO status (lock icon)

- [ ] Export PDF button
  - [ ] Button: "Esporta PDF"
  - [ ] GET /schedule/{week}/export-pdf
  - [ ] Download tabellone.pdf
  - [ ] Show layout: classes on rows, time grid, teacher names in cells

### API Calls
```
POST   /schedule/generate                  (solve)
GET    /schedule/{week_start}              (load)
POST   /schedule/{week_start}/modify-slot  (warm-start modify)
POST   /chat/send                          (SSE stream)
GET    /chat/history/{schedule_id}         (load chat)
POST   /schedule/{week_start}/approve      (finalize)
GET    /schedule/{week_start}/export-pdf   (download)
```

---

## Common Components (~2-3 hours)

- [ ] Navigation bar
  - [ ] Breadcrumbs: Setup → Disponibilità → Dashboard
  - [ ] School name + year display
  - [ ] Logout button

- [ ] Loading spinner
  - [ ] Custom loader for API calls
  - [ ] Timeout indicator

- [ ] Error/success toast notifications
  - [ ] Show validation errors
  - [ ] Show save confirmations
  - [ ] Auto-dismiss after 3s

- [ ] Responsive layout
  - [ ] Desktop: 2-3 columns
  - [ ] Tablet: Stacked sections
  - [ ] Mobile: Full-width (optional for v1)

---

## Tech Stack (Recommended)

- **Framework:** React 18+ or Next.js 14+
- **State:** React Context API or Zustand (keep it simple)
- **HTTP:** Axios or fetch with retry logic
- **SSE:** EventSource API (browser built-in)
- **Styling:** Tailwind CSS or CSS Modules
- **Components:** Headless UI or shadcn/ui (buttons, dropdowns, modals)
- **Table:** TanStack Table (react-table) for tabellone
- **Forms:** React Hook Form + Zod for validation
- **Icons:** Heroicons or Lucide React

---

## Integration Checklist

- [ ] Setup auth context (_get_current_school_id from user session)
- [ ] Configure API base URL (http://localhost:8000 for dev)
- [ ] Add error boundary + global error handler
- [ ] Add request interceptor for auth token
- [ ] Setup logging for debugging

---

## Testing Checklist

- [ ] Unit test: CSV parser (validate file content)
- [ ] Integration test: Upload → Validate → Save flow
- [ ] E2E test: Full setup + generate schedule + approve
- [ ] UI test: Schedule table renders correctly
- [ ] Chat test: SSE events stream properly

---

## Performance Targets

- [ ] Page load: <2s
- [ ] API response: <1s (except solver, 60s timeout)
- [ ] Schedule table: Render 500 cells <100ms
- [ ] Chat: SSE latency <200ms

---

## Accessibility (Nice-to-Have)

- [ ] Keyboard navigation (Tab, Enter, Arrow keys)
- [ ] Screen reader support (ARIA labels)
- [ ] High contrast mode
- [ ] Font sizing options

---

## Future Enhancements (v2+)

- [ ] PDF OCR import (upload calendario PDF)
- [ ] Mobile app (React Native)
- [ ] Multi-language support (it, en)
- [ ] Advanced analytics (weekly reports)
- [ ] Docenti portal (view their schedule)

---

**Ready to start? Confirm backend is running: `curl http://localhost:8000/docs`**
