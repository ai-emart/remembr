#!/usr/bin/env bash
# =============================================================================
# Remembr — First-time Docker setup
# Usage:  bash scripts/docker-init.sh
# Idempotent: safe to re-run after the first setup.
# =============================================================================
set -euo pipefail

COMPOSE="${DOCKER_COMPOSE:-docker compose}"
SERVER_URL="${REMEMBR_URL:-http://localhost:8000}"

log() { echo "[remembr-init] $*"; }
die() { echo "[remembr-init] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Start infrastructure (Postgres, Redis, Ollama) before the server
# ---------------------------------------------------------------------------
log "Starting infrastructure services..."
$COMPOSE up -d postgres redis ollama

# ---------------------------------------------------------------------------
# 2. Pull the embedding model (runs ollama-init, which exits 0 when done)
# ---------------------------------------------------------------------------
log "Pulling Ollama embedding model (nomic-embed-text) — this may take a few minutes on first run..."
$COMPOSE up ollama-init
# ollama-init exits 0 on success; compose exits with its code

# ---------------------------------------------------------------------------
# 3. Start PgBouncer and the API server
# ---------------------------------------------------------------------------
log "Starting PgBouncer and server..."
$COMPOSE up -d pgbouncer server

# ---------------------------------------------------------------------------
# 4. Wait for the server to be healthy
# ---------------------------------------------------------------------------
log "Waiting for server to be healthy..."
MAX_RETRIES=30
RETRY=0
until curl -sf "${SERVER_URL}/health" > /dev/null 2>&1; do
  RETRY=$((RETRY + 1))
  if [ "$RETRY" -ge "$MAX_RETRIES" ]; then
    die "Server did not become healthy after ${MAX_RETRIES} attempts. Check: $COMPOSE logs server"
  fi
  log "  attempt ${RETRY}/${MAX_RETRIES} — waiting 5s..."
  sleep 5
done
log "Server is healthy."

# ---------------------------------------------------------------------------
# 5. Run database migrations (idempotent via Alembic)
# ---------------------------------------------------------------------------
log "Running database migrations..."
$COMPOSE exec -T server alembic upgrade head

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
log ""
log "Setup complete!"
log "  API:    ${SERVER_URL}"
log "  Health: curl ${SERVER_URL}/health"
log ""
log "Next steps:"
log "  1. Register: curl -X POST ${SERVER_URL}/api/v1/auth/register -H 'Content-Type: application/json' -d '{\"email\":\"you@example.com\",\"password\":\"secret\",\"name\":\"You\"}'"
log "  2. See QUICKSTART.md for full walkthrough"
log ""
log "To stop:            $COMPOSE down"
log "To stop + wipe data: $COMPOSE down -v"
