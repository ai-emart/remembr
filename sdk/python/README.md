# Remembr Python SDK

`remembr` is the official Python SDK for Remembr. It gives Python applications a typed async client for sessions, memory storage, search, checkpoints, export, and forget workflows.

## Install

```bash
pip install remembr
```

`EMBEDDING_PROVIDER=sentence_transformers` is the default for bare installs, so you do not need a `JINA_API_KEY` just to get started locally.

## Quick Start

```python
import asyncio

from remembr import RemembrClient


async def main() -> None:
    async with RemembrClient(
        api_key="your-api-key",
        base_url="http://localhost:8000/api/v1",
    ) as client:
        session = await client.create_session(
            metadata={"user": "demo", "context": "support"}
        )

        await client.store(
            content="User prefers Friday billing summaries.",
            role="user",
            session_id=session.session_id,
            tags=["kind:preference", "topic:billing"],
        )

        results = await client.search(
            query="When should billing summaries be sent?",
            session_id=session.session_id,
            limit=5,
            search_mode="hybrid",
            weights={"semantic": 0.6, "keyword": 0.3, "recency": 0.1},
        )

        for memory in results.results:
            print(memory.content, memory.score)


asyncio.run(main())
```

## Local Server Setup

```bash
git clone https://github.com/ai-emart/remembr.git
cd remembr
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
# paste the generated value into SECRET_KEY in .env
bash scripts/docker-init.sh
curl http://localhost:8000/health
```

The Docker bootstrap flow works without Jina. For a plain Python install outside Docker, the default embedding backend is `sentence_transformers`.

## Configuration

```python
from remembr import RemembrClient

client = RemembrClient(
    api_key="your-api-key",
    base_url="http://localhost:8000/api/v1",
    timeout=30.0,
)
```

## Environment Variables

| Variable | Purpose | Required | Default |
| --- | --- | --- | --- |
| `REMEMBR_API_KEY` | Default API key for the client | No | None |
| `REMEMBR_BASE_URL` | Default API base URL | No | `http://localhost:8000/api/v1` |
| `EMBEDDING_PROVIDER` | Active embedding backend for self-hosted deployments | No | `sentence_transformers` |
| `SENTENCE_TRANSFORMERS_MODEL` | Local sentence-transformers model | No | `all-MiniLM-L6-v2` |
| `JINA_API_KEY` | Jina API key when using the Jina backend | No | None |
| `OLLAMA_BASE_URL` | Ollama base URL when using the Ollama backend | No | `http://localhost:11434` |
| `OPENAI_API_KEY` | OpenAI API key when using the OpenAI backend | No | None |

## Docs

- Full docs: https://github.com/ai-emart/remembr/tree/main/docs
- Quick start: https://github.com/ai-emart/remembr#quick-start
- API reference: https://github.com/ai-emart/remembr/blob/main/docs/api-reference.md
- Framework adapters: https://github.com/ai-emart/remembr/tree/main/adapters
