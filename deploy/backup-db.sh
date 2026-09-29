#!/usr/bin/env bash
# Dumps the Postgres database to deploy/backups/ (gitignored). Safe to run
# on a cron - e.g. `0 3 * * * /path/to/deploy/backup-db.sh` for a nightly
# backup, since it doesn't touch the running containers.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p deploy/backups
STAMP=$(date -u +%Y%m%d-%H%M%S)
OUT="deploy/backups/calendariodocenti-${STAMP}.sql.gz"

docker compose --env-file .env.production exec -T postgres \
  pg_dump -U "$(grep -oP '(?<=^POSTGRES_USER=).*' .env.production)" \
           "$(grep -oP '(?<=^POSTGRES_DB=).*' .env.production)" \
  | gzip > "$OUT"

echo "Backup written to $OUT"

# Keep the last 30 backups, drop older ones.
ls -1t deploy/backups/calendariodocenti-*.sql.gz 2>/dev/null | tail -n +31 | xargs -r rm --
