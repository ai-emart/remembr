# Contributing

Thanks for helping build Remembr.

## Getting started

```bash
git clone https://github.com/ai-emart/remembr.git
cd remembr
python -m venv .venv
```

Install the backend and SDK in editable mode, then start the Docker stack:

```bash
pip install -r server/requirements.txt
pip install -e sdk/python
bash scripts/docker-init.sh
```

## Workflow

- Open an issue for large changes before implementation
- Prefer explicit, readable code over clever shortcuts
- Keep async and sync boundaries clean
- Never commit secrets
- Never delete a test without replacing it

## Validation

```bash
cd server && pytest
ruff check server sdk/python adapters examples
bash scripts/check-docs.sh
```

Run adapter-local tests when touching an adapter.

## Style

- Python 3.11+
- `ruff` for linting
- `pytest` for tests
- `alembic` for migrations
- Conventional commit messages are preferred

## Docs

Documentation changes should update examples, method signatures, and deployment instructions in the same pass whenever behavior changes.
