# Calendario Docenti

Piattaforma AI-powered per la generazione e gestione dell'orario scolastico settimanale
(istituti superiori / IeFP). Combina un motore di ottimizzazione vincolata (OR-Tools
CP-SAT) con un copilota conversazionale per la revisione dell'orario. Specifiche
complete in [`specs.md`](specs.md).

Monorepo: backend in [`app/`](app), frontend in [`frontend/`](frontend).

## Struttura

```
app/                  Backend FastAPI (Python)
  domain/             Logica di dominio pura: solver OR-Tools, parser CSV, validator, NLP chat
  repositories/        Accesso al DB (SQLAlchemy), disaccoppiato dalla logica di dominio
  services/            Orchestrazione business logic per route
  routes/               Endpoint FastAPI (setup, availability, schedule, chat)
  models.py             Modelli SQLAlchemy (schema PostgreSQL)
  schemas.py            Modelli Pydantic per request/response

frontend/             Frontend React + TanStack Router/Query + Tailwind
  src/routes/          Pagine: setup, disponibilità docenti, orario/dashboard
  src/lib/api.ts        Client HTTP verso il backend
```

## Avvio backend

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configura app/config.py / .env: DATABASE_URL punta a un'istanza PostgreSQL
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Documentazione interattiva su `http://localhost:8000/docs`. Tutti gli endpoint sono
sotto il prefisso `/api` (es. `POST /api/schedule/generate`), tranne `GET /health`.

### Test automatici (backend)

```bash
pip install -r requirements-dev.txt
pytest
```

I test in [`tests/`](tests) girano contro un file SQLite temporaneo (nessun PostgreSQL
richiesto) e coprono: solver OR-Tools (vincoli rigidi/soft, classi accoppiate, giorni di
chiusura/stage), parsing NLP della chat, validazione dati di setup, parsing del
calendario PDF (con un PDF sintetico generato al volo via reportlab, per non dipendere
da file reali di una scuola), e tutti gli endpoint `/api/*` end-to-end (setup →
disponibilità → generazione/approvazione orario → chat). Diversi test sono di
regressione su bug già corretti (es. classi accoppiate mai schedulate, pesi dei vincoli
soft ignorati, `scuola_id` non coerente dopo il setup).

Nota: v1 è single-tenant e admin-only — non c'è ancora autenticazione, tutte le route
usano una `scuola_id` fissa (`"sch_1"`) impostata durante `/api/setup/save`.

## Avvio frontend

```bash
cd frontend
npm install
npm run dev
```

Il client legge l'URL del backend da `VITE_API_BASE_URL` (vedi `frontend/src/lib/api.ts`).

## Stato del progetto

- **Backend**: implementati setup/onboarding (parsing CSV **e PDF** + validazione +
  salvataggio — vedi sotto), gestione disponibilità docenti, generazione orario via
  OR-Tools (vincoli rigidi: niente doppie prenotazioni, capienza giornaliera per
  classe/gruppo, classi accoppiate, disponibilità docenti, esclusione stage, esclusione
  chiusure straordinarie, monte ore residuo; vincoli soft: max ore teoria consecutive,
  distribuzione uniforme del monte ore nelle settimane residue, riduzione buche per i
  contrattisti), approvazione orario, export PDF (placeholder), chat con parsing NLP a
  pattern (senza LLM reale).
- **Frontend**: pagine setup, disponibilità e orario/dashboard con copilota chat,
  collegate al backend reale (non più mock).
- Il flusso end-to-end (setup → disponibilità → generazione orario → approvazione →
  export → chat) è stato verificato con dati di prova generati casualmente, incluso il
  rispetto delle chiusure straordinarie e delle classi accoppiate.
- Non ancora implementati: autenticazione/multi-tenant, memoria AI persistente delle
  preferenze, azioni rapide di deroga e modifica-slot con ricalcolo reale, generazione
  PDF effettiva (WeasyPrint), alcuni endpoint di comodo usati dal frontend
  (`/api/teachers`, `/api/availability/weeks`, `/schedule/{week}/regenerate`).

### Calendario annuale: CSV o PDF (specs.md 3.1)

`POST /api/calendar/upload` accetta sia CSV che **PDF**. Il parser PDF
(`CalendarParser.parse_calendario_pdf`, in `app/domain/parser.py`) è scritto su misura
per il layout "CALENDARIO AF" usato da questa scuola: una tabella con una riga per
giorno scolastico e colonne di ore giornaliere per 5 gruppi-anno (PRIME/SECONDE/
TERZE/QUARTE/PRIMA4+2). Funziona interamente offline (pdfplumber, nessuna chiave API
richiesta), estraendo le parole per posizione (x, y) invece di affidarsi al
riconoscimento automatico delle tabelle di pdfplumber, che su questo file unisce righe
diverse; se in futuro cambia il template del calendario, le colonne x hardcoded in
`CALENDARIO_PDF_GRUPPI_COLONNE` andranno riadattate.

Ore diverse per gruppo-anno richiedono una `Classe` con un campo `gruppo` che
corrisponda a una delle colonne (es. `PRIME`) — impostabile con una colonna opzionale
`gruppo` nel CSV delle classi. Una `CalendarioAnnuale` con `gruppo=NULL` si applica a
tutta la scuola (comportamento invariato per chi usa solo CSV); i giorni feriali assenti
dalla tabella PDF vengono trattati come chiusura automaticamente.

Non estratte dal PDF (lasciate al CSV/all'admin): i periodi di tirocinio espliciti e gli
eventi (riunioni, scrutini, ecc.) presenti nella tabella accanto — il loro effetto pratico
sulla disponibilità delle classi coincide comunque con le celle vuote della griglia
giornaliera, già gestite.

## Documentazione aggiuntiva

- [`specs.md`](specs.md) — specifiche funzionali complete
- [`BACKEND_DESIGN.md`](BACKEND_DESIGN.md), [`FRONTEND_DESIGN.md`](FRONTEND_DESIGN.md) — design di dettaglio
- [`QUICK_START.md`](QUICK_START.md) — guida ai test manuali del backend (alcuni esempi curl sono
  antecedenti al prefisso `/api` e ad alcune correzioni recenti alle richieste, es. il body
  JSON di `/api/schedule/generate`; fare riferimento a `/docs` per i contratti attuali)
