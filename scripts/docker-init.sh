#!/usr/bin/env bash
# =============================================================================
# Remembr — First-time Docker setup
# Usage:  bash scripts/docker-init.sh
# Idempotent: safe to re-run after the first setup.
# =============================================================================
set -euo pipefail

COMPOSE="${DOCKER_COMPOSE:-docker compose}"
SERVER_URL="${REMEMBR_URL:-http://localhost:8000}"
PROVIDER="${EMBEDDING_PROVIDER:-ollama}"

log() { echo "[remembr-init] $*"; }
die() { echo "[remembr-init] ERROR: $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. Start core infrastructure (Postgres, Redis, PgBouncer)
# ---------------------------------------------------------------------------
log "Starting core infrastructure (postgres, redis, pgbouncer)..."
$COMPOSE up -d postgres redis pgbouncer

# ---------------------------------------------------------------------------
# 2. If using Ollama, start it and pull the embedding model
# ---------------------------------------------------------------------------
if [ "$PROVIDER" = "ollama" ]; then
  log "Starting Ollama..."
  $COMPOSE up -d ollama

  log "Pulling Ollama embedding model (nomic-embed-text) — this may take a few minutes on first run..."
  $COMPOSE up ollama-init
  # ollama-init exits 0 on success; compose exits with its code
else
  log "EMBEDDING_PROVIDER=$PROVIDER — skipping Ollama startup."
fi

# ---------------------------------------------------------------------------
# 3. Start the API server, worker, and beat scheduler
# ---------------------------------------------------------------------------
log "Starting server, worker, and scheduler..."
$COMPOSE up -d server worker worker-beat

# ---------------------------------------------------------------------------
# 4. Wait for the server to be healthy
# ---------------------------------------------------------------------------
log "Waiting for server to be healthy..."
MAX_RETRIES=30
RETRY=0
until curl -sf "${SERVER_URL}/api/v1/health" > /dev/null 2>&1; do
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
log "  API:    ${SERVER_URL}/api/v1"
log "  Health: curl ${SERVER_URL}/api/v1/health"
log ""
log "Next steps:"
log "  1. Register: curl -X POST ${SERVER_URL}/api/v1/auth/register \\"
log "       -H 'Content-Type: application/json' \\"
log "       -d '{\"email\":\"you@example.com\",\"password\":\"secret\",\"org_name\":\"My Org\"}'"
log "  2. See QUICKSTART.md for the full walkthrough"
log ""
log "To stop:            $COMPOSE down"
log "To stop + wipe data: $COMPOSE down -v"
