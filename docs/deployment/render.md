# Render Deployment

Render can run Remembr with a Docker web service plus worker services.

## Working `render.yaml`

```yaml
services:
  - type: web
    name: remembr-server
    env: docker
    dockerfilePath: server/Dockerfile
    dockerContext: .
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: remembr-postgres
          property: connectionString
      - key: REDIS_URL
        fromService:
          type: redis
          name: remembr-redis
          property: connectionString
      - key: SECRET_KEY
        generateValue: true
      - key: EMBEDDING_PROVIDER
        value: ollama
      - key: OLLAMA_BASE_URL
        value: https://your-ollama-endpoint
      - key: OLLAMA_EMBEDDING_MODEL
        value: nomic-embed-text
    startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT

  - type: worker
    name: remembr-worker
    env: docker
    dockerfilePath: server/Dockerfile
    dockerContext: .
    startCommand: celery -A app.celery_app worker --loglevel=info --concurrency=2

  - type: worker
    name: remembr-worker-beat
    env: docker
    dockerfilePath: server/Dockerfile
    dockerContext: .
    startCommand: celery -A app.celery_app beat --loglevel=info

databases:
  - name: remembr-postgres

  - name: remembr-redis
    databaseName: remembr
    ipAllowList: []
```

After first boot:

```bash
alembic upgrade head
```

