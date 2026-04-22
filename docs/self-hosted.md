# Self-Hosted

Self-hosting Remembr V1 means running the server, workers, Postgres with `pgvector`, Redis, and an embedding backend. The reference path is Docker Compose.

## Recommended path

1. Copy `.env.example` to `.env`
2. Generate and set `SECRET_KEY`
3. Run `bash scripts/docker-init.sh`
4. Create a user and API key
5. Point your SDK or adapter at `http://localhost:8000/api/v1`

## Default services

- `postgres`
- `pgbouncer`
- `redis`
- `ollama`
- `ollama-init`
- `server`
- `worker`
- `worker-beat`

## Environment highlights

```env
DATABASE_URL=postgresql+asyncpg://remembr:remembr@pgbouncer:6432/remembr
REDIS_URL=redis://redis:6379
EMBEDDING_PROVIDER=sentence_transformers
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

Add `JINA_API_KEY` or `OPENAI_API_KEY` only if you switch providers.

## Production notes

- Put TLS and authz in front of the service
- Keep `/admin` off the public internet
- Back up Postgres regularly
- Scale workers separately from the API
