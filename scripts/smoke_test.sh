#!/usr/bin/env bash
# End-to-end smoke test of a running stack: health, login, authenticated API call,
# frontend page. Usage: scripts/smoke_test.sh [base_url] [email] [password]
set -euo pipefail
BASE="${1:-http://localhost:8080}"
EMAIL="${2:-admin@example.com}"
PASSWORD="${3:-admin1234}"

echo "waiting for $BASE/health ..."
for _ in $(seq 1 60); do
  curl -fsS "$BASE/health" >/dev/null 2>&1 && break
  sleep 2
done
curl -fsS "$BASE/health" | grep -q '"ok"'
echo "health ok"

TOKEN=$(curl -fsS -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
test -n "$TOKEN"
echo "login ok"

curl -fsS "$BASE/api/auth/me" -H "Authorization: Bearer $TOKEN" | grep -q "$EMAIL"
echo "authenticated API ok"

curl -fsS "$BASE/" | grep -qi "<html"
echo "frontend ok"
echo "SMOKE TEST PASSED"
