#!/usr/bin/env bash
# First start, or rebuild + restart after a code change. Run from anywhere.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -f .env.production ]; then
  echo ".env.production not found - run deploy/generate-secrets.sh first, then edit DOMAIN in it." >&2
  exit 1
fi

docker compose --env-file .env.production up -d --build
echo
echo "Up. 'docker compose logs -f' to follow logs, deploy/create-admin.sh to add the first admin account."
