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

- **Backend**: implementati setup/onboarding (parsing CSV + validazione + salvataggio),
  gestione disponibilità docenti, generazione orario via OR-Tools (vincoli rigidi:
  niente doppie prenotazioni, capienza giornaliera, classi accoppiate, disponibilità
  docenti, esclusione stage, esclusione chiusure straordinarie, monte ore residuo;
  vincoli soft: max ore teoria consecutive, distribuzione uniforme del monte ore nelle
  settimane residue, riduzione buche per i contrattisti), approvazione orario, export
  PDF (placeholder), chat con parsing NLP a pattern (senza LLM reale).
- **Frontend**: pagine setup, disponibilità e orario/dashboard con copilota chat,
  collegate al backend reale (non più mock).
- Il flusso end-to-end (setup → disponibilità → generazione orario → approvazione →
  export → chat) è stato verificato con dati di prova generati casualmente, incluso il
  rispetto delle chiusure straordinarie e delle classi accoppiate.
- Non ancora implementati: autenticazione/multi-tenant, memoria AI persistente delle
  preferenze, azioni rapide di deroga e modifica-slot con ricalcolo reale, generazione
  PDF effettiva (WeasyPrint), alcuni endpoint di comodo usati dal frontend
  (`/api/teachers`, `/api/availability/weeks`, `/schedule/{week}/regenerate`).

## Documentazione aggiuntiva

- [`specs.md`](specs.md) — specifiche funzionali complete
- [`BACKEND_DESIGN.md`](BACKEND_DESIGN.md), [`FRONTEND_DESIGN.md`](FRONTEND_DESIGN.md) — design di dettaglio
- [`QUICK_START.md`](QUICK_START.md) — guida ai test manuali del backend (alcuni esempi curl sono
  antecedenti al prefisso `/api` e ad alcune correzioni recenti alle richieste, es. il body
  JSON di `/api/schedule/generate`; fare riferimento a `/docs` per i contratti attuali)
