# Remembr — Self-Hosted Quick Start

Get Remembr running locally in under 5 minutes — no API keys required.

---

## Prerequisites

| Requirement | Version |
|-------------|---------|
| **Docker** & **Docker Compose** | v20+ / v2+ |
| **curl** | Any recent version |

That's it. Embeddings run locally via Ollama.

---

## 1. Clone the Repository

```bash
git clone https://github.com/ai-emart/remembr.git
cd remembr
```

## 2. Configure Environment

```bash
cp .env.example .env
```

Open `.env` and set a secret key:

```bash
# Required — generate a secret key for JWT authentication
SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
```

All other defaults are pre-configured for the Docker Compose setup.
No Jina AI key or any other API key is needed.

## 3. First-Time Setup (one command)

```bash
bash scripts/docker-init.sh
```

This script:
1. Starts PostgreSQL, Redis, and Ollama
2. Pulls the `nomic-embed-text` embedding model (~274 MB, once only)
3. Starts PgBouncer (connection pooler) and the API server
4. Runs database migrations

When it finishes you'll see:

```
[remembr-init] Setup complete!
[remembr-init]   API:    http://localhost:8000
```

> **Subsequent starts** (after the first): just `docker compose up -d`.
> The model is already cached in the `ollama_data` volume.

## 4. Verify with Health Check

```bash
curl http://localhost:8000/health
```

Expected response:

```json
{"status": "ok", "environment": "local", "version": "0.1.0"}
```

## 5. Services Running

| Service | Port | Description |
|---------|------|-------------|
| **PostgreSQL** (pgvector) | 5432 | Long-term episodic memory storage |
| **PgBouncer** | 6432 | Connection pooler (transaction mode) |
| **Redis** | 6379 | Short-term memory cache & rate limiting |
| **Ollama** | 11434 | Local embedding inference |
| **Remembr Server** | 8000 | FastAPI REST API |

## 6. Register Your First User and Get an API Key

**Register:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "you@example.com",
    "password": "your-secure-password",
    "name": "Your Name"
  }'
```

**Login to get a JWT token:**

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "you@example.com",
    "password": "your-secure-password"
  }'
```

Save the `access_token` from the response.

**Create an API key:**

```bash
curl -X POST http://localhost:8000/api/v1/api-keys \
  -H "Authorization: Bearer <your-access-token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "my-first-key", "scope": "agent"}'
```

Save the returned API key — you'll use it with the SDK.

## 7. First Memory Store and Search

**Install the Python SDK:**

```bash
pip install remembr
```

**Store and search a memory:**

```python
import asyncio
from remembr import RemembrClient

async def main():
    client = RemembrClient(
        api_key="your-api-key",
        base_url="http://localhost:8000/api/v1"
    )

    # Create a session
    session = await client.create_session(
        metadata={"user": "demo", "context": "quickstart"}
    )

    # Store a memory
    await client.store(
        content="User prefers email notifications on Fridays",
        role="user",
        session_id=session.session_id,
        tags=["preference", "notification"]
    )

    # Search memories
    results = await client.search(
        query="When should I send notifications?",
        session_id=session.session_id,
        limit=5,
        mode="hybrid"
    )

    for memory in results.results:
        print(f"[{memory.role}] {memory.content} (score: {memory.score:.3f})")

    await client.aclose()

asyncio.run(main())
```

---

## Using a Different Embedding Provider

The default is Ollama (local). To switch providers, set `EMBEDDING_PROVIDER` in `.env`:

```bash
# Jina AI (cloud, high quality)
EMBEDDING_PROVIDER=jina
JINA_API_KEY=jina_...

# OpenAI
EMBEDDING_PROVIDER=openai
OPENAI_API_KEY=sk-...

# sentence-transformers (local, no GPU needed, no Ollama)
EMBEDDING_PROVIDER=sentence_transformers
```

See [server/EMBEDDINGS.md](server/EMBEDDINGS.md) for the full provider guide.

---

## Stopping Services

```bash
docker compose down
```

To also remove all data volumes (start fresh):

```bash
docker compose down -v
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| **Health check fails** | `docker compose ps` — check all containers are running |
| **Database connection error** | Wait 10–15s for PostgreSQL to initialize, then retry |
| **Embedding errors (Ollama)** | Model may still be pulling. Check: `docker compose logs ollama-init` |
| **Port conflicts** | Edit port mappings in `docker-compose.yml` |
| **Slow first start** | Normal — Ollama downloads ~274 MB model on first run |

---

## Next Steps

- Read the [README](README.md) for full documentation
- Explore the [API Reference](docs/api-reference.md)
- Try [framework adapters](adapters/) for LangChain, CrewAI, and more
- See [CONTRIBUTING.md](CONTRIBUTING.md) to get involved
