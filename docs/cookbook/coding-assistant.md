# Coding Assistant

A coding assistant benefits from memory when it needs to preserve project decisions, known errors, and review feedback across runs.

## Suggested tags

- `kind:decision`
- `kind:bug`
- `kind:feedback`
- `repo:remembr`
- `surface:adapter`

## Example

```python
import asyncio

from remembr import RemembrClient


async def main() -> None:
    async with RemembrClient(api_key="YOUR_API_KEY") as client:
        session = await client.create_session(metadata={"repo": "remembr"})
        await client.store(
            "LangGraph adapter must pass idempotency_key from thread and checkpoint IDs.",
            role="assistant",
            session_id=session.session_id,
            tags=["kind:decision", "surface:adapter"],
        )
        results = await client.search("What do we require for LangGraph writes?", session_id=session.session_id)
        print(results.results[0].content)


asyncio.run(main())
```

