#!/usr/bin/env bash
# Creates (or resets the password of) the school admin account - see
# scripts/create_admin.py. Run after the first `deploy/up.sh`.
# Usage: deploy/create-admin.sh admin@scuola.it "una password robusta"
set -euo pipefail
cd "$(dirname "$0")/.."

if [ $# -lt 2 ]; then
  echo "Usage: $0 <email> <password>" >&2
  exit 1
fi

docker compose --env-file .env.production exec backend python -m scripts.create_admin "$1" "$2"
