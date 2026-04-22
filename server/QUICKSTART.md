# Quick Start Guide

## Prerequisites

1. Python 3.11 or higher installed
2. PostgreSQL with pgvector extension
3. Redis instance (or Upstash account)

## Setup Steps

### 1. Install Dependencies

```bash
cd server
pip install -e ".[dev]"
```

### 2. Configure Environment

```bash
# Copy example environment file
cp .env.example .env

# Edit .env and set required variables
# Minimum required:
# - DATABASE_URL
# - REDIS_URL
# - SECRET_KEY (generate with: openssl rand -hex 32)
# - EMBEDDING_PROVIDER (defaults to sentence_transformers)
# - JINA_API_KEY only when EMBEDDING_PROVIDER=jina
```

### 3. Start the Server

Option A - Using uvicorn directly:
```bash
uvicorn app.main:app --reload
```

Option B - Using the run script:
```bash
python run.py
```

Option C - Custom port:
```bash
python run.py --port 8080
```

### 4. Verify It's Running

```bash
# Check health endpoint
curl http://localhost:8000/api/v1/health

# Expected response:
# {
#   "status": "ok",
#   "environment": "local",
#   "version": "0.1.0"
# }
```

### 5. View API Documentation

Open in your browser:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Running Tests

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=app --cov-report=html

# Run specific test file
pytest app/test_main.py -v
```

## Common Issues

### Import Errors

If you get import errors, make sure you installed the package in editable mode:
```bash
pip install -e ".[dev]"
```

### Database Connection Errors

Verify your `DATABASE_URL` is correct and PostgreSQL is running:
```bash
psql $DATABASE_URL -c "SELECT version();"
```

### Redis Connection Errors

Test your Redis connection:
```bash
redis-cli -u $REDIS_URL ping
```

## Next Steps

- Add your first API endpoint in `app/api/v1/router.py`
- Configure database models in `app/models/`
- Add business logic in `app/services/`
- Set up Alembic migrations for database schema
