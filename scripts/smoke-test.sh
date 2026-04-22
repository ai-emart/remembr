#!/usr/bin/env bash
# =============================================================================
# Remembr — CI smoke test
# Brings up the stack, exercises the API, tears down.
#
# Usage:
#   bash scripts/smoke-test.sh               # full stack (requires Docker)
#   SKIP_COMPOSE=1 bash scripts/smoke-test.sh  # test against running stack
# =============================================================================
set -euo pipefail

COMPOSE="${DOCKER_COMPOSE:-docker compose}"
SERVER_URL="${REMEMBR_URL:-http://localhost:8000}"
SKIP_COMPOSE="${SKIP_COMPOSE:-0}"

log()  { echo "[smoke] $*"; }
pass() { echo "[smoke] PASS: $*"; }
fail() { echo "[smoke] FAIL: $*" >&2; exit 1; }

cleanup() {
  if [ "$SKIP_COMPOSE" = "0" ]; then
    log "Tearing down..."
    $COMPOSE down -v --remove-orphans 2>/dev/null || true
  fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# 1. Boot the stack (skip if already running)
# ---------------------------------------------------------------------------
if [ "$SKIP_COMPOSE" = "0" ]; then
  log "Starting stack..."
  # Use sentence_transformers for CI — no model pull needed
  EMBEDDING_PROVIDER=sentence_transformers $COMPOSE up -d --wait postgres redis pgbouncer server 2>/dev/null || \
    $COMPOSE up -d postgres redis pgbouncer server
fi

# ---------------------------------------------------------------------------
# 2. Wait for server health
# ---------------------------------------------------------------------------
log "Waiting for server health..."
MAX=40
for i in $(seq 1 "$MAX"); do
  if curl -sf "${SERVER_URL}/health" > /dev/null 2>&1; then
    break
  fi
  if [ "$i" -eq "$MAX" ]; then fail "Server not healthy after ${MAX} attempts"; fi
  sleep 3
done

# ---------------------------------------------------------------------------
# 3. Health endpoint
# ---------------------------------------------------------------------------
HEALTH=$(curl -sf "${SERVER_URL}/health")
log "Health response: $HEALTH"
echo "$HEALTH" | grep -q '"status"' || fail "/health did not return status field"
pass "/health OK"

# ---------------------------------------------------------------------------
# 4. Register a test user
# ---------------------------------------------------------------------------
TS=$(date +%s)
EMAIL="smoke-${TS}@test.local"
PASS="smoke-pass-${TS}"
ORG_NAME="Smoke Test Org ${TS}"

REG=$(curl -sf -X POST "${SERVER_URL}/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASS}\",\"org_name\":\"${ORG_NAME}\"}" || \
  fail "Registration request failed")
log "Register response: $REG"
echo "$REG" | grep -q '"access_token"' || fail "Registration did not return auth tokens"
pass "Register OK"

# ---------------------------------------------------------------------------
# 5. Login
# ---------------------------------------------------------------------------
LOGIN=$(curl -sf -X POST "${SERVER_URL}/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASS}\"}" || \
  fail "Login request failed")
TOKEN=$(echo "$LOGIN" | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
[ -n "$TOKEN" ] || fail "No access_token in login response"
pass "Login OK (token length: ${#TOKEN})"

# ---------------------------------------------------------------------------
# 6. Create API key
# ---------------------------------------------------------------------------
APIKEY_RESP=$(curl -sf -X POST "${SERVER_URL}/api/v1/api-keys" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"name":"smoke-key"}' || \
  fail "API key creation failed")
API_KEY=$(echo "$APIKEY_RESP" | grep -o '"api_key":"[^"]*"' | cut -d'"' -f4)
[ -n "$API_KEY" ] || fail "No key in API key response"
pass "API key created"

# ---------------------------------------------------------------------------
# 7. Create a session
# ---------------------------------------------------------------------------
SESSION_RESP=$(curl -sf -X POST "${SERVER_URL}/api/v1/sessions" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"metadata":{"source":"smoke-test"}}' || \
  fail "Session creation failed")
SESSION_ID=$(echo "$SESSION_RESP" | grep -o '"session_id":"[^"]*"' | cut -d'"' -f4)
[ -n "$SESSION_ID" ] || fail "No session_id in session response"
pass "Session created"

# ---------------------------------------------------------------------------
# 8. Store a memory episode
# ---------------------------------------------------------------------------
STORE=$(curl -sf -X POST "${SERVER_URL}/api/v1/memory" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"role\":\"user\",\"content\":\"The smoke test ran successfully at ${TS}\",\"session_id\":\"${SESSION_ID}\",\"tags\":[\"smoke\",\"test\"]}" || \
  fail "Memory store failed")
log "Store response: $STORE"
echo "$STORE" | grep -q '"episode_id"' || fail "Store did not return episode id"
pass "Memory store OK"

# ---------------------------------------------------------------------------
# 9. Fetch the session context
# ---------------------------------------------------------------------------
SESSION_DETAIL=$(curl -sf "${SERVER_URL}/api/v1/sessions/${SESSION_ID}" \
  -H "X-API-Key: ${API_KEY}" || \
  fail "Session detail fetch failed")
echo "$SESSION_DETAIL" | grep -q 'Live\|smoke test ran successfully\|The smoke test ran successfully' || \
  fail "Session detail did not return stored message"
pass "Session detail OK"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
log ""
log "All smoke tests passed."
