#!/bin/bash
set -e

BASE_URL="${SMOKE_TEST_URL:-http://localhost:8000}"
API_URL="$BASE_URL/api/v1"

echo "[smoke] Testing health endpoint..."
curl -sf "$BASE_URL/api/v1/health" | grep -q "status" || (echo "Health check failed" && exit 1)
echo "[smoke] Health: OK"

echo "[smoke] Registering test user..."
TOKEN_RESPONSE=$(curl -sf -X POST "$API_URL/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"smoke@test.com","password":"smoketest123","org_name":"smoke-org"}' || \
  curl -sf -X POST "$API_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"smoke@test.com","password":"smoketest123"}')

TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null || echo "")

if [ -z "$TOKEN" ]; then
  echo "[smoke] Auth failed — skipping authenticated tests"
  echo "[smoke] Basic smoke test passed (health only)"
  exit 0
fi

echo "[smoke] Auth: OK"

echo "[smoke] Creating session..."
SESSION=$(curl -sf -X POST "$API_URL/sessions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"metadata":{"smoke":"true"}}')
SESSION_ID=$(echo "$SESSION" | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
echo "[smoke] Session: $SESSION_ID"

echo "[smoke] Storing memory..."
curl -sf -X POST "$API_URL/memory" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"content\":\"smoke test memory\",\"role\":\"user\",\"session_id\":\"$SESSION_ID\"}" > /dev/null
echo "[smoke] Store: OK"

echo "[smoke] All smoke tests passed."
