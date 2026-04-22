# Remembr

[![CI](https://github.com/ai-emart/remembr/actions/workflows/ci.yml/badge.svg)](https://github.com/ai-emart/remembr/actions/workflows/ci.yml)
[![PyPI version](https://img.shields.io/pypi/v/remembr)](https://pypi.org/project/remembr/)
[![npm version](https://img.shields.io/npm/v/@remembr/sdk)](https://www.npmjs.com/package/@remembr/sdk)
[![License](https://img.shields.io/github/license/ai-emart/remembr)](LICENSE)
[![Python versions](https://img.shields.io/pypi/pyversions/remembr)](https://pypi.org/project/remembr/)

Remembr gives AI agents durable, searchable memory with a simple `store`, `search`, and `delete` workflow, session-aware context, and a self-hosted stack you can run locally in minutes.

## Quick Start

```bash
git clone https://github.com/ai-emart/remembr.git
cd remembr
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
# paste the generated value into SECRET_KEY in .env
bash scripts/docker-init.sh
curl http://localhost:8000/health
```

`JINA_API_KEY` is optional for local setup. For bare installs, `EMBEDDING_PROVIDER=sentence_transformers` is the default. The Docker bootstrap script starts the full local stack, including PostgreSQL, Redis, PgBouncer, Ollama, the API server, and migrations.

See [QUICKSTART.md](QUICKSTART.md) for the full self-hosted walkthrough.

## Install The SDKs

```bash
pip install remembr
npm install @remembr/sdk
```

## Python Example

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
            content="User prefers email notifications on Fridays",
            role="user",
            session_id=session.session_id,
            tags=["preference", "notification"],
        )

        results = await client.search(
            query="When should I send notifications?",
            session_id=session.session_id,
            limit=5,
            search_mode="hybrid",
            weights={"semantic": 0.6, "keyword": 0.3, "recency": 0.1},
        )

        for memory in results.results:
            print(f"[{memory.role}] {memory.content} (score: {memory.score:.3f})")


asyncio.run(main())
```

## TypeScript Example

```typescript
import { RemembrClient } from '@remembr/sdk';

async function main() {
  const client = new RemembrClient({
    apiKey: process.env.REMEMBR_API_KEY!,
    baseUrl: 'http://localhost:8000/api/v1'
  });

  const session = await client.createSession({
    user: 'demo',
    context: 'support'
  });

  await client.store({
    content: 'User prefers dark mode interface',
    role: 'user',
    sessionId: session.session_id,
    tags: ['preference', 'ui']
  });

  const results = await client.search({
    query: 'What are the user UI preferences?',
    sessionId: session.session_id,
    limit: 5,
    searchMode: 'hybrid',
    weights: { semantic: 0.6, keyword: 0.3, recency: 0.1 }
  });

  results.results.forEach((memory) => {
    console.log(`[${memory.role}] ${memory.content} (score: ${memory.score})`);
  });
}

main();
```

## Environment Variables

| Variable | Purpose | Required | Default |
| --- | --- | --- | --- |
| `DATABASE_URL` | PostgreSQL connection string | Yes | `postgresql://postgres:postgres@localhost:5432/remembr` |
| `REDIS_URL` | Redis connection string | Yes | `redis://localhost:6379` |
| `SECRET_KEY` | JWT signing secret | Yes | None |
| `EMBEDDING_PROVIDER` | Embedding backend: `sentence_transformers`, `jina`, `ollama`, or `openai` | Yes | `sentence_transformers` |
| `SENTENCE_TRANSFORMERS_MODEL` | Local sentence-transformers model name | No | `all-MiniLM-L6-v2` |
| `JINA_API_KEY` | Jina API key when `EMBEDDING_PROVIDER=jina` | No | None |
| `JINA_EMBEDDING_MODEL` | Jina embedding model | No | `jina-embeddings-v3` |
| `OLLAMA_BASE_URL` | Ollama base URL when `EMBEDDING_PROVIDER=ollama` | No | `http://localhost:11434` |
| `OLLAMA_EMBEDDING_MODEL` | Ollama embedding model | No | `nomic-embed-text` |
| `OPENAI_API_KEY` | OpenAI API key when `EMBEDDING_PROVIDER=openai` | No | None |
| `OPENAI_EMBEDDING_MODEL` | OpenAI embedding model | No | `text-embedding-3-small` |
| `OTEL_ENABLED` | Enable OpenTelemetry export | No | `false` |
| `OTEL_EXPORTER_ENDPOINT` | OTLP exporter endpoint | No | None |

## Docs

- [Docs index](docs/index.md)
- [Framework quickstarts](docs/quickstart/langchain.md)
- [API reference](docs/api-reference.md)
- [Self-hosting guide](docs/self-hosted.md)
- [Python SDK README](sdk/python/README.md)
- [TypeScript SDK README](sdk/typescript/README.md)
