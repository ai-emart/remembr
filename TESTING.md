# Testing Guide

## Overview

Remembr uses pytest for testing with a minimum coverage requirement of 70%.

## Test Structure

```
server/tests/
├── __init__.py
├── test_config.py          # Configuration tests
├── test_health.py          # Health check endpoint tests
├── test_middleware.py      # Middleware tests
└── test_error_handling.py  # Error handling tests
```

## Running Tests

### Prerequisites

Start test services using Docker Compose:

```bash
docker-compose -f docker-compose.test.yml up -d
```

Or manually:

```bash
# PostgreSQL + pgvector
docker run -d -p 5433:5432 \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=remembr_test \
  pgvector/pgvector:pg16

# Redis
docker run -d -p 6379:6379 redis:7
```

### Set Environment Variables

```bash
export DATABASE_URL=postgresql://postgres:postgres@localhost:5433/remembr_test
export REDIS_URL=redis://localhost:6379
export SECRET_KEY=test-secret-key
export JINA_API_KEY=test-jina-key
export ENVIRONMENT=local
export LOG_LEVEL=DEBUG
```

### Run All Tests

```bash
cd server
pytest tests/ -v
```

### Run Specific Test File

```bash
pytest tests/test_health.py -v
```

### Run Specific Test

```bash
pytest tests/test_health.py::test_health_check_success -v
```

### Run with Coverage

```bash
# Terminal report
pytest tests/ -v --cov=app --cov-report=term-missing

# HTML report
pytest tests/ -v --cov=app --cov-report=html

# View HTML report
open htmlcov/index.html  # macOS
xdg-open htmlcov/index.html  # Linux
start htmlcov/index.html  # Windows
```

### Run with Coverage Threshold

```bash
# Fail if coverage is below 70%
pytest tests/ -v --cov=app --cov-fail-under=70
```

## Writing Tests

### Test File Naming

- Test files must start with `test_`
- Test functions must start with `test_`
- Test classes must start with `Test`

### Example Test

```python
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    """Create test client."""
    app = create_app()
    return TestClient(app)


def test_endpoint(client):
    """Test description."""
    response = client.get("/api/v1/endpoint")
    
    assert response.status_code == 200
    assert response.json()["key"] == "value"
```

### Using Fixtures

```python
@pytest.fixture
def sample_data():
    """Provide sample data for tests."""
    return {
        "id": 1,
        "name": "Test",
    }


def test_with_fixture(client, sample_data):
    """Test using fixture."""
    response = client.post("/api/v1/items", json=sample_data)
    assert response.status_code == 201
```

### Async Tests

```python
import pytest


@pytest.mark.asyncio
async def test_async_function():
    """Test async function."""
    result = await some_async_function()
    assert result is not None
```

## Test Categories

### Unit Tests

Test individual functions and classes in isolation:

```python
def test_function_logic():
    """Test pure function logic."""
    result = my_function(input_data)
    assert result == expected_output
```

### Integration Tests

Test multiple components working together:

```python
def test_api_endpoint_with_database(client, db_session):
    """Test endpoint that uses database."""
    response = client.post("/api/v1/items", json={"name": "Test"})
    assert response.status_code == 201
    
    # Verify in database
    item = db_session.query(Item).first()
    assert item.name == "Test"
```

### Marking Tests

```python
@pytest.mark.slow
def test_slow_operation():
    """Test that takes a long time."""
    pass


@pytest.mark.integration
def test_integration():
    """Integration test."""
    pass
```

### Live Docker-Backed Integration Tests

Some server tests are intentionally wired to live local Docker services instead of
in-memory fakes. These are marked with `live_integration` and currently cover:

- auth to API key to short-term Redis-backed memory flow
- outbound webhook delivery over real local HTTP

Run only that slice with:

```bash
cd server
pytest -m live_integration -v
```

Run specific markers:

```bash
# Skip slow tests
pytest -m "not slow"

# Run only integration tests
pytest -m integration

# Run only live Docker-backed integration tests
pytest -m live_integration
```

## Coverage Configuration

Coverage is configured in `server/.coveragerc`:

- Source: `app/` directory
- Omit: Test files, `__pycache__`, virtual environments
- Minimum: 70%

### Excluded from Coverage

Lines with these comments are excluded:

```python
def debug_function():  # pragma: no cover
    """Only used for debugging."""
    pass
```


## End-to-End (E2E) Tests

E2E tests live in `tests/e2e/` and run against real Remembr infrastructure.

### E2E Environment Variables

```bash
export REMEMBR_E2E_API_KEY=<org api key>
export REMEMBR_E2E_BASE_URL=http://localhost:8000/api/v1

# Optional for multi-tenant isolation test
export REMEMBR_E2E_API_KEY_ORG_A=<org A key>
export REMEMBR_E2E_API_KEY_ORG_B=<org B key>

# Optional cleanup target for forget_user
export REMEMBR_E2E_USER_ID=<uuid>
```

### Run E2E Suite Locally

```bash
pytest tests/e2e -v
```

If `REMEMBR_E2E_API_KEY` is not set, the entire E2E suite is skipped.

## Continuous Integration

GitHub Actions runs unit/integration tests automatically on:
- Push to `main` branch
- Pull requests to `main` branch

E2E tests run **only** on pushes to `main` (never on pull requests).

CI is skipped for:
- Changes to `*.md` files
- Changes to `docs/` directory

### CI Environment

- Python 3.11
- PostgreSQL 15
- Redis 7
- Coverage threshold: 70%

## Troubleshooting

### Tests Fail with Database Connection Error

Ensure PostgreSQL is running:

```bash
docker ps | grep postgres
```

Test connection:

```bash
psql postgresql://postgres:postgres@localhost:5433/remembr_test -c "SELECT 1"
```

### Tests Fail with Redis Connection Error

Ensure Redis is running:

```bash
docker ps | grep redis
```

Test connection:

```bash
redis-cli -h localhost -p 6379 ping
```

### Import Errors

Install the package in editable mode:

```bash
cd server
pip install -e ".[dev]"
```

### Coverage Below Threshold

Identify uncovered lines:

```bash
pytest --cov=app --cov-report=term-missing
```

Add tests for uncovered code or mark as `# pragma: no cover` if appropriate.

### Slow Tests

Run with timing information:

```bash
pytest --durations=10
```

Mark slow tests:

```python
@pytest.mark.slow
def test_slow_operation():
    pass
```

Skip slow tests:

```bash
pytest -m "not slow"
```

## Best Practices

1. **One assertion per test** (when possible)
2. **Use descriptive test names** that explain what is being tested
3. **Arrange-Act-Assert** pattern:
   ```python
   def test_example():
       # Arrange
       data = {"key": "value"}
       
       # Act
       result = function(data)
       
       # Assert
       assert result == expected
   ```
4. **Use fixtures** for common setup
5. **Mock external services** (databases, APIs, etc.)
6. **Test edge cases** and error conditions
7. **Keep tests fast** - use mocks for slow operations
8. **Test behavior, not implementation**

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [FastAPI testing](https://fastapi.tiangolo.com/tutorial/testing/)
- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
