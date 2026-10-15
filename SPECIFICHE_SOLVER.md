# Specifiche del solver: regole, priorità e strategia di ricerca — 15 ottobre 2026

Obiettivo: un'unica fonte che elenca **tutte** le regole dell'orario, in che ordine di priorità cedono, come si
verifica che siano rispettate e con quale strategia di ricerca CP-SAT si cerca la soluzione. Completa `specs.md` §9
(che per `teoria_consecutive` riporta ancora il peso 10: il valore reale è 3000 + 10, vedi sotto) e aggiunge la
regola dei 3 ore minime per i contratti. Il benchmark non ha modificato il solver; gli interventi vincenti sono stati poi applicati (sezione 1b).

## 1. Benchmark delle strategie di ricerca

Script: `scripts/benchmark/solver_strategies.py` (sola lettura sul DB). Risultati grezzi:
`scripts/benchmark/risultati_2026-10-15.jsonl`. Stesso modello (`ScheduleSolver.build_model`) per tutte le
varianti, quindi l'obiettivo è confrontabile; cambia solo **come** si cerca. 60 s, 16 worker, pesi attivi del DB locale,
settimane 2026-10-19 e 2026-10-26, nessuna ora scoperta in nessuna prova.

Variazione dell'obiettivo rispetto alla baseline (parametri di default), più basso = meglio:

| Variante | 19/10 | 26/10 | Media |
|---|---|---|---|
| `linearization_level=2` | −1,2% | −2,8% | **−2,0%** |
| baseline ripetuta (misura del rumore) | 0,0% | −2,1% | −1,1% |
| 8 worker | −0,6% | −0,1% | −0,4% |
| `linearization_level=0` | +2,2% | −2,6% | −0,2% |
| due fasi (regole poi preferenze) | +4,0% | −3,5% | +0,2% |
| `optimize_with_core` | +1,0% | −0,4% | +0,3% |
| `symmetry_level=2` | +0,1% | +0,5% | +0,3% |
| solo LNS | +2,2% | −1,4% | +0,4% |
| 4 seed × 15 s | +3,0% | −1,1% | +0,9% |
| senza core / senza probing | +3,5% / −0,5% | −0,4% / +3,7% | +1,6% |

**Come leggerli.** Il rumore tra due run identiche arriva al 2% (settimana 26/10: 42.621 contro 41.717), quindi
nessuna differenza sotto il 2% è dimostrata. Due conclusioni reggono: (1) nessuna variante migliora la baseline di più
di circa il 2–3%; (2) lo scarto dal bound resta ~10% con ogni parametro. I parametri di ricerca non sono la leva.

**Scelta consigliata:** una sola ricerca da 60 s con 16 worker e `linearization_level = 2` (migliore o seconda in entrambe le
settimane e, in media, trova la sua soluzione migliore prima: 17 s e 24 s contro 26–59 s). Il guadagno è modesto e
va riconfermato su più settimane prima di considerarlo certo. Da **non** adottare: campionamento a più seed e ricerca
in due fasi (non migliorano e il primo spezza il tempo), `symmetry_level=2`, senza core.

**Dove sta il margine vero.** L'obiettivo è dominato da `ore_target_deviation` e `paired_hours_override`
(circa 23–27 e 12–15 penalità attive su ~8.000), cioè da come è formulato il target ore, non dalla ricerca. L'analisi
del 7 ottobre (`REPORT_ANALISI_SOLVER.md` §5) misurava il modello OPTIMAL in 1,9 s senza il target ore. Gli interventi
proposti lì (O1, O3, O5, O6) restano il prossimo passo e **non sono stati provati in questo benchmark**.

## 1b. Interventi sul modello (test separato, 15/10)

Script `scripts/benchmark/solver_model_variants.py`, risultati `scripts/benchmark/risultati_modello_2026-10-15.jsonl`.
Ogni variante risolve un modello diverso (60 s, 16 worker, settimane 19/10 e 26/10); la soluzione è poi **rivalutata col modello di
produzione**. Poiché il target ore è proprio ciò che alcune varianti cambiano, il confronto onesto è sulle **regole** (obiettivo
di produzione meno la parte «target ore») e sul numero di rotture di «max 1 ora in coppia». Media delle due settimane:

| Variante | Obiettivo senza target ore | Coppie rotte | Assegnazioni con scarto dal target |
|---|---|---|---|
| produzione | 16.463 | 13,5 | 23,5 |
| hint dalla bozza salvata | 17.130 | 13,5 | 21,0 |
| scarto massimo 2% (`relative_gap_limit`) | 15.697 | 13,0 | 23,0 |
| target riportato alla capienza della classe | 16.716 | 14,0 | 33,0 |
| **tolleranza ±1 ora sul target** | **14.071** | **11,5** | 57,0 |
| capienza + tolleranza | 13.811 | 11,5 | 51,0 |
| capienza + tolleranza + `linearization_level=2` | 13.386 | 11,0 | 46,5 |

- **Funziona:** la tolleranza di ±1 ora riduce di circa il 15% le rotture della regola sulle coppie e il costo delle altre regole
  (−14%). È l'unico intervento con un effetto oltre il rumore. Il prezzo: più assegnazioni finiscono a 1 ora dal target, per
  scelta. Non ho misurato se qualcuna superi 1 ora di scarto.
- **Non funziona:** `relative_gap_limit` 2% (lo scarto reale è ~10%, non si ferma prima), hint dalla bozza (la bozza salvata è
  vecchia, la prima soluzione non migliora), target riportato alla capienza da solo (nessun guadagno sulle regole).
- **Limite strutturale:** 11 coppie rotte sembrano un minimo: tre varianti diverse si fermano esattamente lì in entrambe le
  settimane. Con le regole attuali e gli abbinamenti attuali circa 11 giorni-docente richiedono comunque più di 1 ora in coppia.
  Per scendere servono una deroga mirata o un cambio dei dati/accoppiamenti, non una strategia di ricerca.
- **Decisione che spetta all'admin:** la tolleranza ±1 ora contraddice la regola attuale «ore esatte» (decisione 2026-10).
  Applicata il 15/10 su richiesta (branch `solver-tolleranza-ore`): tolleranza ±1 ora (`TARGET_TOLERANCE_HOURS`), target riportati alla capienza
  della classe (`_target_scale_by_classe`) e `linearization_level = 2`. Prova reale a 60 s: 257 lezioni, 11 coppie rotte, 2–4 conflitti sul target ore.

## 2. Ordine di priorità (chi cede per primo)

1. Ore di classe non coperte / oltre capienza — peso **1500** (mai scambiate con una preferenza).
2. Vincoli quasi rigidi — peso **1000**, sempre con deroga e sempre segnalati.
3. Regole forti con peso proprio: `teoria_consecutive` **3000 + 10** per finestra da 3 ore.
4. Target ore settimanale esatto — **500 + 15** per ora di scarto (× 0,5…1,5 per i contratti).
5. Preferenze — peso regolabile, massimo 200.

Nota: la regola 3 sta sopra la 2 e la 4 per decisione dell'admin (commit 866464a); `specs.md` §9.4 va aggiornato.

## 3. Catalogo completo delle regole

### Rigide (mai violate)
| Id | Regola |
|---|---|
| H1 | Un docente non è in due classi nella stessa ora (eccetto lezione accoppiata) |
| H1b | Una classe ha al più una lezione per ora |
| H2 | Capienza esatta: ore della classe nel giorno = ore massime del giorno |
| H2b | Le lezioni di una classe in un giorno sono un unico blocco contiguo |
| H2c | Nessuna lezione prima di `ora_inizio_min` della classe |
| H3 | Le coppie hanno lo stesso docente, giorno e ora nelle due classi; il monte ore scala una volta |
| H4 | Contrattista mai dove non è disponibile (in generazione) |
| H5 | Classi in stage: zero lezioni |
| H6 | Assunto: ore per assegnazione ≤ residuo (il contrattista può superarlo) |

### Quasi rigide (peso 1000, deroga per sbloccarle)
| Id | Regola | Deroga |
|---|---|---|
| H9 | Il venerdì le classi iniziano alle 8:00 | `authorize_friday_late_start` |
| H10 | Pratica: blocco di almeno min(3, capienza) ore (oggi inattiva: tutte le materie sono TEORIA) | `authorize_short_pratica_block` |
| H11 | Al massimo 4 ore al giorno con la stessa classe | `authorize_single_classe_day` |
| H12 | Al massimo 1 ora in coppia al giorno per docente | `authorize_paired_hours` |
| **H13 (nuova, 15/10)** | **Contratto: se lavora in un giorno, almeno min(3, ore disponibili quel giorno) ore** | `authorize_short_contract_day` |

### Preferenze
| Id | Regola | Peso |
|---|---|---|
| S1 | Max 2 ore consecutive di teoria con la stessa classe | 3000 + 10 |
| S2 | Ore settimanali = target (residuo / settimane utili) | 500 + 15 |
| S3 | Classe inizia alle 8:00 | 100 |
| S4 | Nessun buco orario per i contratti | 150 (× scarsità) |
| S5 | Niente giornata intera con una sola classe | 10 |
| S6 | Il docente di una coppia ruota tra le ore consecutive | 150 |

## 4. Criteri di accettazione (come verificare «tutte le regole rispettate»)

Per ogni settimana generata:
1. stato `OPTIMAL` o `FEASIBLE`, mai solo best-effort senza motivo;
2. zero conflitti `classe_unfilled`, `classe_over_capacity`, `paired_split`;
3. ogni conflitto di tipo `*_override` ha la deroga corrispondente proposta (nessuna violazione silenziosa);
4. nessuna violazione di H1…H6 (controllabile dalle lezioni salvate, indipendentemente dal modello);
5. H13: per ogni contrattista e giorno con lezioni, ore ≥ min(3, disponibilità del giorno), altrimenti conflitto
   `contract_min_hours_override`;
6. riesecuzione del benchmark: obiettivo entro il 3% della baseline di questo documento (rumore incluso).

## 5. Limiti e punti aperti

- Due sole settimane, un solo run per variante: il rumore (fino al 2%) copre quasi tutte le differenze.
- H13 oggi compare come conflitto già in settimana 19/10 (1 caso): è atteso quando l'unica alternativa lascia aule vuote.
- La regola H13 è per **giorno**; se serve per settimana va cambiata.
- Il punteggio di qualità (§9.6 di `specs.md`) non distingue le penalità «vere» dalle ~8.000 di sicurezza.
- 5 test del repository falliscono già prima di questo lavoro (coppie spezzate, override disponibilità, pratica).
