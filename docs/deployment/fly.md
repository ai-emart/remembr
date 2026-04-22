# Fly.io Deployment

Fly.io is a good fit when you want container-native deployment and explicit process groups.

## Working `fly.toml`

```toml
app = "remembr"
primary_region = "iad"

[build]
  dockerfile = "server/Dockerfile"

[env]
  EMBEDDING_PROVIDER = "ollama"
  OLLAMA_BASE_URL = "https://your-ollama-endpoint"
  OLLAMA_EMBEDDING_MODEL = "nomic-embed-text"

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = false
  auto_start_machines = true
  min_machines_running = 1

[[vm]]
  size = "shared-cpu-1x"

[processes]
  app = "uvicorn app.main:app --host 0.0.0.0 --port 8000"
  worker = "celery -A app.celery_app worker --loglevel=info --concurrency=2"
  beat = "celery -A app.celery_app beat --loglevel=info"
```

## Secrets

```bash
fly secrets set DATABASE_URL=... REDIS_URL=... SECRET_KEY=...
```

Run migrations with a one-off machine:

```bash
fly ssh console -C "cd /app && alembic upgrade head"
```

