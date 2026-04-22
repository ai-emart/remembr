# Docker Deployment

Docker is the default and best-supported way to run Remembr V1.

## What starts

- PostgreSQL with `pgvector`
- PgBouncer
- Redis
- Ollama
- Ollama init job for `nomic-embed-text`
- FastAPI server
- Celery worker
- Celery beat

## Run it

```bash
cp .env.example .env
bash scripts/docker-init.sh
```

## Working config

The root [`docker-compose.yml`](../self-hosted.md) is the reference deployment. The server and workers support:

```env
DATABASE_URL=postgresql+asyncpg://remembr:remembr@pgbouncer:6432/remembr
REDIS_URL=redis://redis:6379
EMBEDDING_PROVIDER=sentence_transformers
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

`JINA_API_KEY` is optional. Set provider-specific keys only when you switch away from the local defaults.

## Verify

```bash
curl http://localhost:8000/health
```

## Notes

- Keep Postgres in Docker. The test suite and default docs assume the containerized `pgvector` stack.
- The admin UI is available at `http://localhost:8000/admin` outside production.
