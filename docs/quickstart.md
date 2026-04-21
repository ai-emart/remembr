# Quickstart (5 minutes)

Get from zero to your first stored + retrieved memory in minutes.

## 1) Install an SDK

### Python
```bash
pip install remembr
```

### TypeScript
```bash
npm install @remembr/sdk
```

## 2) Get an API key

Create an API key in your Remembr dashboard (or via `/v1/api-keys` after auth), then export it:

```bash
export REMEMBR_API_KEY="rk_live_or_test_key"
```

Optional (self-hosted or staging API):

```bash
export REMEMBR_BASE_URL="http://localhost:8000/api/v1"
```

## 3) Store your first memory (Python)

```python
import asyncio
import os
from remembr import RemembrClient


async def main() -> None:
    client = RemembrClient(
        api_key=os.environ["REMEMBR_API_KEY"],
        base_url=os.getenv("REMEMBR_BASE_URL", "http://localhost:8000/api/v1"),
    )
    try:
        session = await client.create_session(metadata={"source": "quickstart-python"})

        await client.store(
            content="I prefer concise status updates every Friday.",
            role="user",
            session_id=session.session_id,
            tags=["preference"],
        )

        result = await client.search(
            query="When should updates be sent?",
            session_id=session.session_id,
            limit=3,
            search_mode="hybrid",
            weights={"semantic": 0.6, "keyword": 0.3, "recency": 0.1},
        )

        for item in result.results:
            print(f"[{item.role}] {item.content} (score={item.score:.3f})")
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
```

## 4) Store + retrieve memory (TypeScript)

```ts
import { RemembrClient } from '@remembr/sdk';

async function main() {
  const client = new RemembrClient({
    apiKey: process.env.REMEMBR_API_KEY!,
    baseUrl: process.env.REMEMBR_BASE_URL ?? 'http://localhost:8000/api/v1',
  });

  const session = await client.createSession({
    metadata: { source: 'quickstart-typescript' },
  });

  await client.store({
    content: 'My preferred database stack is PostgreSQL + pgvector.',
    role: 'user',
    sessionId: session.session_id,
    tags: ['stack'],
  });

  const result = await client.search({
    query: 'Which database stack do I prefer?',
    sessionId: session.session_id,
    limit: 3,
    searchMode: 'hybrid',
    weights: { semantic: 0.6, keyword: 0.3, recency: 0.1 },
  });

  for (const item of result.results) {
    console.log(`[${item.role}] ${item.content} (score=${item.score})`);
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
```

## Next

- Full API Reference: [`docs/api-reference.md`](./api-reference.md)
- Core concepts and scoping: [`docs/concepts.md`](./concepts.md)
- Adapter guides: [`docs/adapters/`](./adapters/)
- Self-hosting: [`docs/self-hosted.md`](./self-hosted.md)
