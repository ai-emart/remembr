# Customer Support Agent

This pattern stores durable preferences, issue history, and resolutions without stuffing every previous exchange back into the prompt.

## Pattern

1. Create one session per support conversation.
2. Store durable facts with structured tags such as `kind:preference` and `kind:resolution`.
3. Search with `tag_filters` before each answer.
4. Soft-delete or export data when the customer asks.

```python
import asyncio

from remembr import RemembrClient, TagFilter


async def main() -> None:
    async with RemembrClient(api_key="YOUR_API_KEY") as client:
        session = await client.create_session(metadata={"channel": "support"})
        await client.store(
            "Customer wants Friday billing summaries.",
            role="user",
            session_id=session.session_id,
            tags=["kind:preference", "topic:billing"],
        )
        results = await client.search(
            "How should we send billing updates?",
            session_id=session.session_id,
            tag_filters=[TagFilter(key="kind", value="preference")],
        )
        print(results.total)


asyncio.run(main())
```

