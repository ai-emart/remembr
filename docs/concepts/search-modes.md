# Search Modes

Remembr supports three retrieval modes.

## `semantic`

Embedding-only search. Best when wording changes but meaning stays the same.

## `keyword`

Lexical search. Best for exact terms, IDs, log lines, and structured phrases.

## `hybrid`

Default mode. Combines semantic, keyword, and recency scoring. This is usually the right default for agent memory.

## Custom weights

```python
import asyncio

from remembr import RemembrClient, SearchWeights


async def main() -> None:
    async with RemembrClient(api_key="YOUR_API_KEY") as client:
        results = await client.search(
            "customer reported oauth timeout",
            search_mode="hybrid",
            weights=SearchWeights(semantic=0.5, keyword=0.4, recency=0.1),
        )
        print(results.total)


asyncio.run(main())
```

Weights must sum to `1.0`.

