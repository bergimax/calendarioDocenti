# Deploy in produzione (VM gratuita + Docker Compose)

Stack: **Postgres** + **backend** (FastAPI/OR-Tools/WeasyPrint) + **frontend**
(TanStack Start) + **Caddy** (reverse proxy, HTTPS automatico via Let's
Encrypt). Backend e frontend non pubblicano porte proprie sulla macchina:
solo Caddy è raggiungibile dall'esterno (80/443), tutto il resto parla solo
sulla rete Docker interna — niente firewall da configurare porta per porta.

Pensato per una **VM Oracle Cloud "Always Free"** (gratuita per sempre, non
un trial), ma funziona su qualsiasi VM/server Linux con Docker.

Tutto quello descritto qui è già stato testato in locale (build delle
immagini, avvio dello stack, migrazione di un dump reale) prima di essere
consegnato.

---

## 1. Creare la VM (Oracle Cloud Always Free)

Questo passo va fatto da te: richiede la tua identità/verifica, non posso
farlo al posto tuo.

1. Crea un account su [cloud.oracle.com](https://cloud.oracle.com) (serve una
   carta per la verifica, ma restando nei limiti "Always Free" non viene
   addebitato nulla). A volte l'iscrizione viene rifiutata per "capacità non
   disponibile" nella regione scelta — se succede, riprova più tardi o scegli
   un'altra regione (es. Francoforte, Amsterdam invece di Milano).
2. **Create a VM Instance** → scegli:
   - **Image**: Ubuntu 24.04 (più semplice da amministrare di Oracle Linux)
   - **Shape**: `VM.Standard.A1.Flex` (ARM, Always Free fino a 4 OCPU/24GB —
     abbondante per Postgres + OR-Tools + WeasyPrint). È la shape più
     richiesta: se la creazione fallisce con *"Out of capacity for shape
     VM.Standard.A1.Flex"*, prova un'altra regione (Francoforte, Amsterdam,
     Zurigo...) o passa a `VM.Standard.E2.1.Micro` (AMD, sempre Always
     Free, quasi sempre disponibile subito, ma solo 1 OCPU/1GB RAM — vedi
     la nota sotto, **richiede lo swap file del passo 3bis**)
   - **Add SSH keys**: genera o incolla la tua chiave pubblica (`ssh-keygen`
     in locale se non ne hai già una)
3. Nella VCN/Security List creata insieme alla VM, aggiungi due *Ingress
   Rules*: `0.0.0.0/0` → porta **80** (TCP) e `0.0.0.0/0` → porta **443**
   (TCP). Senza questo, Caddy non è raggiungibile da internet anche se la VM
   è su.
4. Annota l'**IP pubblico** della VM (dalla pagina dell'istanza).

**Punto dolente noto di Oracle Cloud**: oltre alla Security List (a livello
di rete), le immagini Ubuntu/Oracle Linux hanno spesso un firewall anche
dentro la VM (`iptables`/`netfilter`) che blocca comunque 80/443. Sulla VM,
dopo il primo accesso SSH:

```bash
sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || true
```

### 1bis. Se sei finito su `VM.Standard.E2.1.Micro` (1GB RAM)

Postgres + il solver OR-Tools + WeasyPrint + Node insieme possono superare
1GB durante la generazione di un orario. Senza swap, il kernel Linux uccide
a caso il container che sta usando più memoria in quel momento (di solito
postgres) invece di limitarsi a rallentare — un click su "Genera orario"
potrebbe far cadere il database. Prima di `deploy/up.sh`, sulla VM:

```bash
deploy/setup-swap.sh
```

Aggiunge 4GB di swap (persistente ai riavvii). Il generatore sarà più lento
sotto carico (swap invece di RAM vera), ma non va più in crash. Se in
seguito Oracle libera capacità A1.Flex, conviene ricreare la VM su quella
shape: `deploy/dump-local-db.sh` + `restore-db.sh` rendono la migrazione
rapida.

---

## 2. Dominio (necessario per HTTPS automatico)

Caddy richiede un **dominio pubblico** che risolva verso l'IP della VM per
poter richiedere un certificato Let's Encrypt — un HTTPS automatico su un
IP nudo non è possibile.

- Se hai già un dominio: crea un record **A** (es. `orario.tuascuola.it` →
  IP della VM).
- Se non vuoi comprarne uno: un sottodominio gratuito va benissimo, es.
  [DuckDNS](https://www.duckdns.org) (`tuascuola.duckdns.org` → IP della VM,
  gratis, pochi minuti).

Il DNS deve **già puntare** alla VM prima del primo avvio, altrimenti la
richiesta del certificato fallisce (Caddy riprova automaticamente, quindi
basta aggiornare il DNS e aspettare qualche minuto/riavviare `caddy`).

---

## 3. Installare Docker sulla VM

```bash
ssh ubuntu@<IP-DELLA-VM>

curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# rientra nella sessione SSH perché il gruppo abbia effetto:
exit
ssh ubuntu@<IP-DELLA-VM>
docker compose version   # conferma che il plugin compose c'è
```

---

## 4. Portare il codice sulla VM

```bash
git clone https://github.com/bergimax/calendarioDocenti.git
cd calendarioDocenti
```

(o `git pull` se stai aggiornando una copia già clonata in precedenza).

---

## 5. Configurare i segreti

```bash
deploy/generate-secrets.sh
nano .env.production   # imposta DOMAIN=orario.tuascuola.it (o il tuo dominio/sottodominio)
```

Lo script genera da solo una password Postgres robusta e casuale — non va
mai scritta a mano né condivisa in chat. `ANTHROPIC_API_KEY` va lasciata
vuota a meno che tu non voglia il copilota IA in chat attivo (vedi nota sui
costi più sotto).

---

## 6. Primo avvio

```bash
deploy/up.sh
```

La prima volta scarica le immagini base e compila backend/frontend — con
OR-Tools/WeasyPrint può richiedere qualche minuto. Verifica:

```bash
curl -I https://orario.tuascuola.it/health
```

Deve rispondere `200`. Se Caddy non ha ancora ottenuto il certificato
(dominio troppo recente, o DNS non ancora propagato), guarda i log:

```bash
docker compose --env-file .env.production logs -f caddy
```

---

## 7. Portare i dati reali della scuola (consigliato)

Il database Postgres locale di sviluppo ha già docenti, classi, disponibilità
e gli orari generati finora. Meglio migrare quello che ripartire da zero:

**Sulla tua macchina di sviluppo:**
```bash
deploy/dump-local-db.sh
scp deploy/handoff-dump.sql.gz ubuntu@<IP-DELLA-VM>:~/calendarioDocenti/deploy/
```

**Sulla VM:**
```bash
deploy/restore-db.sh deploy/handoff-dump.sql.gz
```

Il dump include già l'account admin creato in sviluppo
(`admin@calendariodocenti.local`) — login immediato dopo il restore, non
serve `create-admin.sh`.

### In alternativa: scuola nuova, da zero

Se invece è una scuola diversa senza dati pregressi:

```bash
deploy/create-admin.sh admin@scuola.it "una password robusta"
```

poi login e usa il wizard di setup in-app (`/setup`) per caricare i CSV
della scuola — vedi `QUICK_START.md` per il formato atteso.

---

## 8. Verifica finale

Apri `https://orario.tuascuola.it` nel browser, fai login, controlla che
l'orario esistente sia visibile e che "Genera orario" funzioni (il solver
impiega tipicamente 30-60 secondi).

---

## Manutenzione

**Aggiornare il codice** (quando ricevi nuove funzionalità/fix):
```bash
deploy/update.sh
```
Fa `git pull` + ricostruisce solo le immagini cambiate + riavvia.

**Backup del database** (consigliato: schedulato via cron):
```bash
deploy/backup-db.sh
# crontab -e, poi aggiungi:
# 0 3 * * * cd /home/ubuntu/calendarioDocenti && deploy/backup-db.sh >> deploy/backup.log 2>&1
```
Tiene gli ultimi 30 backup in `deploy/backups/` (fuori da git).

**Log**:
```bash
docker compose --env-file .env.production logs -f backend
docker compose --env-file .env.production logs -f frontend
```

**Riavvio manuale** di un solo servizio:
```bash
docker compose --env-file .env.production restart backend
```

---

## Limiti "Always Free" da rispettare (perché resti a costo zero)

- `VM.Standard.A1.Flex`: non superare **4 OCPU / 24GB RAM** in totale sul
  tenancy (un'unica VM con questi valori resta gratuita).
- 1 IP pubblico riservato incluso; **non** allocarne altri extra.
- 200GB di block storage Always Free totali: il boot volume di default
  (~50GB) ci sta comodamente.
- Nessun costo per banda in uscita entro 10TB/mese — irraggiungibile per
  questo uso.

## Nota sui costi non coperti da questa guida

- **Copilota IA in chat**: richiede `ANTHROPIC_API_KEY` con fatturazione a
  consumo su [console.anthropic.com](https://console.anthropic.com) — non
  gratuito, indipendente dall'hosting. Tutto il resto dell'app (setup,
  disponibilità, generazione orario, export PDF/Excel, azioni rapide)
  funziona comunque senza questa chiave.
- Un dominio a pagamento (se non usi un'opzione gratuita come DuckDNS).
