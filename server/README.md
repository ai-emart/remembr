# Remembr Server

FastAPI-based memory service for AI agents.

## Local Setup

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
# paste the generated value into SECRET_KEY in .env
bash ../scripts/docker-init.sh
```

`JINA_API_KEY` is optional. The embedding backend is controlled by `EMBEDDING_PROVIDER`, which defaults to `sentence_transformers` for bare installs.

## Required Configuration

- `DATABASE_URL`
- `REDIS_URL`
- `SECRET_KEY`
- `EMBEDDING_PROVIDER`

## Optional Provider-Specific Configuration

- `JINA_API_KEY`
- `JINA_EMBEDDING_MODEL`
- `OLLAMA_BASE_URL`
- `OLLAMA_EMBEDDING_MODEL`
- `OPENAI_API_KEY`
- `OPENAI_EMBEDDING_MODEL`
- `SENTENCE_TRANSFORMERS_MODEL`
- `OTEL_ENABLED`
- `OTEL_EXPORTER_ENDPOINT`

## Running The Server Manually

```bash
cd server
alembic upgrade head
uvicorn app.main:app --reload
```

## Verify

```bash
curl http://localhost:8000/health
```

## Testing

```bash
pytest
```
