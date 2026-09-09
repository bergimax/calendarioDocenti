# Specifiche di Progetto: Piattaforma Gestione e Ottimizzazione Orari Scolastici (AI-Powered)

## 1. Visione e Obiettivi del Progetto
La piattaforma ha lo scopo di automatizzare, ottimizzare e gestire la creazione dell'orario scolastico settimanale per istituti superiori ed enti di formazione professionale (AF / IeFP). 

Il sistema combina un motore algoritmico di ottimizzazione vincolata (*Constraint Satisfaction Problem*) con un **Agente AI Conversazionale con memoria a lungo termine**, permettendo all'Amministratore della scuola di perfezionare l'orario tramite comandi in linguaggio naturale, gestire eccezioni quotidiane (malattie/sostituzioni) e supervisionare il monte ore annuale per ciascuna materia e docente.

---

## 2. Tipologie Utente e Permessi (RBAC)

1. **Super-Admin (Manutentore di Sistema):**
   - Gestione Multi-Tenant (creazione e configurazione nuove scuole).
   - Monitoraggio dello stato dei nodi di calcolo, log di errore e metriche globali.
   - Accesso a strumenti di debug per conflitti matematici insormontabili.

2. **School Admin (Amministratore Istituto):**
   - Configurazione annuale (importazione calendario PDF, accoppiamento classi, definizione docenti assunti/contrattisti).
   - Inserimento/revisione disponibilità docenti.
   - Generazione dell'orario settimanale e interazione in chat con l'Agente AI per la risoluzione dei conflitti.
   - Approvazione definitiva dell'orario settimanale ed esportazione tabellone PDF.
   - Gestione assenze e sostituzioni giornaliere in tempo reale.

3. **Docente (Assunto o a Contratto):**
   - Accesso alla propria area riservata (web / mobile-responsive).
   - Visualizzazione del proprio orario settimanale approvato.
   - *Docenti a Contratto:* Inserimento disponibilità oraria tramite griglia visiva interattiva, selezione di 1 classe prioritaria e indicazione delle ore necessarie.
   - Funzione rapida "Conferma orario settimana precedente".

---

## 3. Calendario Scolastico, Monte Ore ed Eccezioni

### 3.1 Parser Intelligente del Calendario Annuale (PDF OCR / AI)
- A inizio anno, l'Amministratore carica il PDF del calendario annuale.
- Un motore di estrazione dati intelligente converte il calendario in dati strutturati nel database:
  - **Feste e chiusure straordinarie.**
  - **Giornate a orario ridotto:** distinzione puntuale per data e classe tra giornate da 4, 5 o 6 ore.
  - **Periodi di Stage / Tirocinio:** intervalli temporali in cui determinate classi sono fuori sede.

### 3.2 Regole di Gestione Stage
- Durante i periodi di stage di una classe, tale classe è **totalmente esclusa dall'assegnazione**.
- I docenti assegnati a quella classe non erogano ore per essa e il relativo monte ore annuale non viene scalato durante lo stage.

### 3.3 Gestione del Monte Ore Annuale
- Ogni materia/classe ha un monte ore annuale prefissato da completare entro fine anno formativo.
- Il sistema genera l'orario **settimana per settimana**:
  - Calcola il pregresso (ore già svolte).
  - Stima il fabbisogno settimanale ideale ("spalmatura uniforme"), ma accetta flessibilità settimanale (es. 0 ore una settimana, 10 ore un'altra) pur di chiudere un orario valido.

---

## 4. Motore di Ottimizzazione e Vincoli (Constraint Engine)

Il motore matematico suddivide i vincoli in due macro-categorie:

### 4.1 Vincoli Rigidi (Hard Constraints - Non Violabili)
1. **Nessuna sovrapposizione docente:** Un docente non può essere assegnato a due classi distinte nella stessa ora (eccetto per classi accoppiate).
2. **Capienza della giornata:** Se un giorno da calendario dura 4 ore, la somma delle lezioni non può superare 4 ore.
3. **Classi Accoppiate:** Per le materie comuni, le due classi assegnate devono avere lezione simultanea con il medesimo docente. Viene scalata **1 sola ora** dal monte ore del docente.
4. **Disponibilità Docenti Assunti:** Fissa dal lunedì al venerdì, fascia 08:00 - 14:00.
5. **Esclusione Stage:** Nessuna lezione programmabile per le classi in tirocinio.

### 4.2 Vincoli Preferenziali (Soft Constraints - Ottimizzabili)
1. **Didattica e Carico Cognitivo:**
   - Materie teoriche: massimo 2 ore consecutive.
   - Materie pratiche/laboratori: blocchi da 3 a 6 ore (adattati alla capienza massima del giorno se la giornata è corta).
   - Posizionamento prioritario delle materie a maggior peso cognitivo nelle prime ore (8:00 - 11:00).
   - Bilanciamento del carico cognitivo giornaliero della classe.
2. **Docenti a Contratto:**
   - Rispetto degli slot indicati nella griglia di disponibilità.
   - Assegnazione della classe prioritaria indicata (se impossibile, assegnazione di ore ridotte).
   - Massimo 2 ore buche settimanali complessive per ciascun contrattista (target ideale: 0 ore buche).
3. **Docenti Assunti:**
   - Preferiti per l'assegnazione delle ore buche rispetto ai contrattisti.
   - Ammesso orario continuativo "no-stop" (fino a 6 ore).
4. **Apprendimento Storico AI:** Preferenze e correzioni memorizzate dalle precedenti sessioni dell'Amministratore.

---

## 5. Agente AI, Memoria e Risoluzione Conflitti

### 5.1 Chat Copilot per l'Amministratore
- L'Amministratore interagisce in linguaggio naturale per richiedere aggiustamenti (es. *"Sposta l'inglese di 2A dal martedì al mercoledì"*).
- L'AI analizza la fattibilità, traduce l'input in vincoli matematici, comanda il ricalcolo e ripresenta la bozza aggiornata.

### 5.2 Memoria Permanente delle Preferenze
- Le direttive ricorrenti (es. *"Il Prof. Neri preferisce non avere lezioni il lunedì prima ora"*) vengono persistite nel profilo della scuola come vincoli soft per le settimane successive.

### 5.3 Gestione degli Scenari Impossibili e Quick Actions
- In caso di insoddisfacibilità dei vincoli, l'AI individua l'insieme minimo di conflitti e fornisce all'Admin:
  - Spiegazione chiara del collo di bottiglia in linguaggio naturale.
  - **Bottoni di Autorizzazione Rapida (Action Buttons):**
    - `[Forza 3 Ore Teoria]`
    - `[Riduci Ore Docente a Contratto]`
    - `[Autorizza Uscita Anticipata Classe]`
    - `[Deroga Disponibilità]`
- L'orario viene ricalcolato all'istante all'attivazione del bottone da parte dell'Admin.

### 5.4 Gestione Live delle Sostituzioni (Malattie)
- L'Admin registra l'assenza improvvisa di un docente per il giorno corrente.
- L'Agente AI valuta le alternative:
  1. Copertura tramite docenti assunti presenti a scuola con ore buche.
  2. Subentro di contrattisti disponibili.
  3. Ricompattamento orario (posticipo ingresso o uscita anticipata della classe).
- L'Admin approva la soluzione con un clic.

---

## 6. Esperienza Utente e Interfaccia (UX/UI)

### 6.1 Portale Docenti a Contratto
- **Griglia Oraria Interattiva:** Visualizzazione settimanale dal Lunedì al Venerdì (fasce orarie verticali). Selezione rapida "click-and-drag" degli intervalli di disponibilità.
- **Pannello Rapido:** Selezione a tendina per 1 Classe Prioritaria e input numerico per Ore Desiderate.
- **Pulsante di Convalida Rapida:** *"Replica disponibilità settimana precedente"*.
- **Meccanismo di Fallback:** Se entro la scadenza settimanale il docente non compila la griglia, il sistema eredita automaticamente l'orario della settimana scorsa.

### 6.2 Dashboard Amministratore
- **Vista Tabellare per Classi:** Colonne = Classi (1A, 2A, 3A...), Righe = Fasce Orarie (1ª ora, 2ª ora...).
- **Celle Dinamiche:**
  - Evidenziazione cromatica per tipologia materia (Teoria vs Pratica/Laboratorio).
  - Celle accoppiate (colspan) estese su più colonne per le lezioni congiunte.
  - Cliccando su un docente, si evidenziano tutte le sue presenze nella settimana.
  - Tooltip con stato del monte ore residuo.
- **Pannello Laterale AI:** Chat interattiva con log delle modifiche e pulsanti di deroga immediata.
- **Pulsante di Approvazione Definitiva:** Rende l'orario ufficiale per la settimana.

### 6.3 Esportazione Finale
- Generazione automatica di un **Unico Tabellone PDF** orizzontale ad alta leggibilità, ottimizzato per stampa e affissione in bacheca/segreteria.
- *(Roadmap v2: Sincronizzazione automatica tramite API con i Registri Elettronici - Spaggiari, ClasseViva, Axios).*

---

## 7. Architettura Dati e Modello Relazionale (Schema Logico)

```
[Tenants/Scuole]
   |-- 1:N --> [Classi]
   |-- 1:N --> [Docenti]
   |             |-- Tipo: ASSUNTO | CONTRATTISTA
   |             |-- 1:N --> [DisponibilitaSettimanali] (Griglia fasce orarie)
   |-- 1:N --> [Materie]
   |             |-- Tipologia: TEORIA | PRATICA
   |             |-- Peso Cognitivo: ALTO | MEDIO | BASSO
   |-- 1:N --> [AccoppiamentiClassi] (Classe_A, Classe_B, MateriaComune)
   |-- 1:N --> [CalendarioAnnuale]
   |             |-- Data, OreMaxGiornata (4/5/6), FlagChiusura, FlagStage (Classe_ID)
   |-- 1:N --> [MonteOreAnnuale]
   |             |-- Classe_ID, Materia_ID, Docente_ID, OreTotali, OreErogate
   |-- 1:N --> [OrarioSettimanale] (Stato: BOZZA | APPROVATO)
                 |-- 1:N --> [SlotLezione] (Giorno, Ora, Classe_ID, Docente_ID, Materia_ID)
                 |-- 1:N --> [MemoriaPreferenzeAI] (Regola, Peso, Contesto)
```

---

## 8. Stack Tecnologico Consigliato

| Componente | Tecnologia Suggerita | Motivazione |
| :--- | :--- | :--- |
| **Frontend** | React / Next.js + Tailwind CSS | Interfaccia reattiva, componenti interattivi (griglia drag-and-drop), server-side rendering per prestazioni veloci. |
| **Backend API** | Python (FastAPI) | Massima velocità, typing nativo, integrazione ideale con librerie di intelligenza artificiale e calcolo scientifico. |
| **Solver Ottimizzazione** | Google OR-Tools (CP-SAT Solver) | Lo standard industriale open source più performante per problemi di Constraint Programming e School Timetabling. |
| **Agente AI & NLP** | Modello LLM avanzato con Function Calling | Capacità di tradurre linguaggio naturale in parametri JSON strutturati per interagire direttamente con OR-Tools. |
| **Database Principale** | PostgreSQL | Robustezza relazionale, supporto JSONB per orari flessibili e compatibilità multi-tenant mediante schemi separati o row-level security. |
| **Generatore PDF** | WeasyPrint / Headless Chrome | Rendering da template HTML/CSS con pieno supporto per layout orizzontali complessi e stili vettoriali. |
| **Archiviazione Documenti**| S3-compatible Object Storage (MinIO / AWS S3) | Storage sicuro per i calendari PDF caricati e i tabelloni generati. |
