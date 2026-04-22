# Railway Deployment

Railway works best by building the existing `server/Dockerfile` and attaching managed Postgres, Redis, and an Ollama-compatible embedding endpoint.

## Recommended topology

- `server` service from `server/Dockerfile`
- `worker` service from the same image
- `worker-beat` service from the same image
- Railway Postgres
- Railway Redis
- External Ollama-compatible endpoint, or swap providers through env vars

## Working `railway.json`

```json
{
  "$schema": "https://railway.app/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "server/Dockerfile"
  },
  "deploy": {
    "numReplicas": 1,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 10
  }
}
```

## Service commands

```text
server: uvicorn app.main:app --host 0.0.0.0 --port $PORT
worker: celery -A app.celery_app worker --loglevel=info --concurrency=2
worker-beat: celery -A app.celery_app beat --loglevel=info
```

## Required environment

```env
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
SECRET_KEY=replace-me
EMBEDDING_PROVIDER=ollama
OLLAMA_BASE_URL=https://your-ollama-endpoint
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

Run `alembic upgrade head` once after the first deploy.

