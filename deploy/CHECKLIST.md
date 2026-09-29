# Checklist primo deploy — Oracle Cloud (VM.Standard.E2.1.Micro)

Percorso specifico scelto in questa sessione: `VM.Standard.A1.Flex` era
"out of capacity", si procede con la shape AMD `VM.Standard.E2.1.Micro`
(1 OCPU/1GB RAM, sempre disponibile, Always Free) + swap file. Guida
completa/generica in [`deploy/README.md`](README.md) — questo è solo
l'elenco spuntabile dei passi per questo caso specifico.

## Fatto

- [x] Chiave SSH generata su questa macchina (`~/.ssh/id_ed25519`).
      Pubblica, da incollare su Oracle:
      ```
      ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAINL6tQgQYuRB1qguvvBYNu+6EaV2PYUBmFa0mN957G6D bergimax@calendariodocenti-deploy
      ```
- [x] Stack Docker preparato, testato e pushato (`deploy/`, `Dockerfile`,
      `docker-compose.yml`, commit `2aee479` + `3da34d2` su `origin/next`).

## Da fare — account e VM

- [ ] Account su [cloud.oracle.com](https://cloud.oracle.com)
- [ ] **Create a VM Instance**:
  - [ ] Image: **Ubuntu 24.04**
  - [ ] Shape: **`VM.Standard.E2.1.Micro`** (AMD, Always Free)
  - [ ] Add SSH keys: incolla la chiave pubblica sopra
  - [ ] Networking → **"Assign a public IPv4 address"** attivo (di norma
        di default su subnet pubblica)
- [ ] Nella Security List della VCN, aggiungi due Ingress Rules
      `0.0.0.0/0`: porta **80** (TCP) e porta **443** (TCP)
- [ ] Annota l'**IP pubblico** dell'istanza

## Da fare — dominio (serve per HTTPS automatico)

Scegli **uno**:
- [ ] Hai già un dominio → crea un record **A** che punti all'IP della VM
- [ ] Non hai un dominio → registrati su [duckdns.org](https://www.duckdns.org)
      (gratis) e crea un sottodominio tipo `tuascuola.duckdns.org` puntato
      all'IP della VM

→ Annota il dominio scelto, serve al passo "generate-secrets" più sotto.

## Da fare — sulla VM (via SSH)

```bash
ssh ubuntu@<IP-PUBBLICO-VM>
```

- [ ] Firewall interno (oltre alla Security List Oracle):
  ```bash
  sudo iptables -I INPUT -p tcp --dport 80 -j ACCEPT
  sudo iptables -I INPUT -p tcp --dport 443 -j ACCEPT
  sudo netfilter-persistent save 2>/dev/null || true
  ```
- [ ] Installa Docker:
  ```bash
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker $USER
  exit
  ```
  poi ri-collegati (`ssh ubuntu@<IP>`) perché il gruppo abbia effetto.
- [ ] Clona il repo:
  ```bash
  git clone https://github.com/bergimax/calendarioDocenti.git
  cd calendarioDocenti
  ```
- [ ] **Swap file (obbligatorio su questa shape da 1GB RAM)**:
  ```bash
  deploy/setup-swap.sh
  ```
- [ ] Genera i segreti e imposta il dominio:
  ```bash
  deploy/generate-secrets.sh
  nano .env.production   # DOMAIN=<il tuo dominio o sottodominio duckdns>
  ```
- [ ] Primo avvio:
  ```bash
  deploy/up.sh
  ```
- [ ] Verifica: `curl -I https://<dominio>/health` → deve rispondere `200`

## Da fare — portare i dati reali della scuola

**Qui, sulla macchina di sviluppo** (non sulla VM):
```bash
cd /home/bergimax/Projects/calendarioDocenti
deploy/dump-local-db.sh
scp deploy/handoff-dump.sql.gz ubuntu@<IP-PUBBLICO-VM>:~/calendarioDocenti/deploy/
```

**Sulla VM**:
```bash
deploy/restore-db.sh deploy/handoff-dump.sql.gz
```

Il dump include già l'admin `admin@calendariodocenti.local` — login
immediato dopo il restore, non serve `create-admin.sh`.

## Verifica finale

- [ ] Apri `https://<dominio>` nel browser, login, controlla che l'orario
      esistente sia visibile
- [ ] Prova "Genera orario" (30-60s, più lento su questa VM per via dello
      swap — normale, non un errore)

## Dopo, se serve

- Aggiornamenti futuri: `deploy/update.sh` (sulla VM)
- Backup DB: `deploy/backup-db.sh`, vedi `deploy/README.md` per il cron
- Se in futuro Oracle libera capacità `VM.Standard.A1.Flex`: si può
  ricreare la VM su quella shape (4 OCPU/24GB, molto più comoda) e
  rimigrare i dati con `dump-local-db.sh`/`restore-db.sh` — non è un
  problema muoversi in un secondo momento.
