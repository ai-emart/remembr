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

REG=$(curl -sf -X POST "${SERVER_URL}/api/v1/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"${EMAIL}\",\"password\":\"${PASS}\",\"name\":\"Smoke Test\"}" || \
  fail "Registration request failed")
log "Register response: $REG"
echo "$REG" | grep -qE '"id"|"email"' || fail "Registration did not return user object"
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
  -d '{"name":"smoke-key","scope":"agent"}' || \
  fail "API key creation failed")
API_KEY=$(echo "$APIKEY_RESP" | grep -o '"key":"[^"]*"' | cut -d'"' -f4)
[ -n "$API_KEY" ] || fail "No key in API key response"
pass "API key created"

# ---------------------------------------------------------------------------
# 7. Store a memory episode
# ---------------------------------------------------------------------------
STORE=$(curl -sf -X POST "${SERVER_URL}/api/v1/memory/episodes" \
  -H "X-API-Key: ${API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{"role":"user","content":"The smoke test ran successfully at '"${TS}"'","tags":["smoke","test"]}' || \
  fail "Memory store failed")
log "Store response: $STORE"
echo "$STORE" | grep -q '"id"' || fail "Store did not return episode id"
pass "Memory store OK"

# ---------------------------------------------------------------------------
# 8. List episodes (tag search — no embeddings required)
# ---------------------------------------------------------------------------
LIST=$(curl -sf "${SERVER_URL}/api/v1/memory/episodes?tags=smoke" \
  -H "X-API-Key: ${API_KEY}" || \
  fail "Episode list failed")
echo "$LIST" | grep -q '"items"' || fail "List did not return items"
pass "Episode list OK"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
log ""
log "All smoke tests passed."
