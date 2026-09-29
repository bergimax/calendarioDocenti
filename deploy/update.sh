#!/usr/bin/env bash
# Pulls the latest committed code and rebuilds/restarts only what changed.
# Run this on the VM when there's a new release to deploy.
set -euo pipefail
cd "$(dirname "$0")/.."

git pull --ff-only
docker compose --env-file .env.production up -d --build
docker image prune -f
echo "Updated and restarted."
