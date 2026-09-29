#!/usr/bin/env bash
# Loads a dump produced by deploy/dump-local-db.sh into the production
# Postgres container. Run this on the VM, after deploy/up.sh has started
# postgres, and BEFORE deploy/create-admin.sh (the dump already includes
# the admin table if one existed locally; if not, create-admin still works
# once the scuola row from the dump is in place).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ $# -lt 1 ]; then
  echo "Usage: $0 <dump-file.sql.gz>" >&2
  exit 1
fi
DUMP="$1"
[ -f "$DUMP" ] || { echo "No such file: $DUMP" >&2; exit 1; }
[ -f .env.production ] || { echo ".env.production not found - run deploy/generate-secrets.sh and deploy/up.sh first." >&2; exit 1; }

PG_USER=$(grep -oP '(?<=^POSTGRES_USER=).*' .env.production)
PG_DB=$(grep -oP '(?<=^POSTGRES_DB=).*' .env.production)

echo "This replaces every table's contents in the '${PG_DB}' database with the dump. Continue? [y/N]"
read -r ans
[ "$ans" = "y" ] || { echo "Aborted."; exit 1; }

gunzip -c "$DUMP" | docker compose --env-file .env.production exec -T postgres psql -U "$PG_USER" -d "$PG_DB"
echo "Restored. Restart the backend so it doesn't hold stale connections: docker compose --env-file .env.production restart backend"
