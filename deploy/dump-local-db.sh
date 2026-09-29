#!/usr/bin/env bash
# Dumps THIS machine's local dev database (the one with the school's real
# data already loaded via scripts/import_documenti.py + the setup/orario
# UI) to a portable file, meant to be copied to the production VM and
# loaded with deploy/restore-db.sh - the actual go-live migration, so the
# client starts with real data instead of an empty school.
#
# Runs pg_dump inside the local dev postgres container (no pg_dump needed
# on the host). Reads its name/user/db from the root .env (DATABASE_URL),
# same as the app itself - see app/config.py.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
  echo ".env not found - this script dumps the LOCAL dev database, run it from a checkout that has one." >&2
  exit 1
fi

DB_URL=$(grep -oP '(?<=^DATABASE_URL=).*' .env)
# postgresql://USER:PASS@HOST:PORT/DB -> USER, DB (container name defaults
# to what QUICK_START.md / this project's dev setup uses).
DB_USER=$(echo "$DB_URL" | sed -E 's#^postgresql://([^:]+):.*#\1#')
DB_NAME=$(echo "$DB_URL" | sed -E 's#.*/([^/?]+)(\?.*)?$#\1#')
CONTAINER="${DEV_DB_CONTAINER:-calendariodocenti-db}"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "Container '$CONTAINER' isn't running. Start it (docker start $CONTAINER) or set DEV_DB_CONTAINER=<name>." >&2
  exit 1
fi

OUT="deploy/handoff-dump.sql.gz"
# --clean --if-exists: the dump drops each table/constraint before
# recreating it, so restore-db.sh is safe to run against a target database
# that already has the (possibly empty, possibly partial) schema in it -
# e.g. because the backend container ran Base.metadata.create_all() on
# first start, before the dump was restored.
docker exec "$CONTAINER" pg_dump --clean --if-exists -U "$DB_USER" "$DB_NAME" | gzip > "$OUT"
echo "Wrote $OUT ($(du -h "$OUT" | cut -f1)). Copy it to the VM, e.g.:"
echo "  scp $OUT youruser@your-vm-ip:~/calendarioDocenti/deploy/"
echo "then on the VM: deploy/restore-db.sh deploy/handoff-dump.sql.gz"
