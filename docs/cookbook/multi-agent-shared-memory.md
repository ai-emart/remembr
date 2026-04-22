# Multi-Agent Shared Memory

Use one session for the workflow run and structured tags per agent so each node can retrieve only the memory slice it needs.

## Why it helps

- Research, writing, and review agents share durable state
- Each agent can query `kind:*` tags instead of replaying the whole transcript
- Review feedback from a previous run can guide the next run

## Example

See the flagship runnable example in [`examples/langgraph-multi-agent`](../index.md).

```python
import asyncio

from remembr import RemembrClient, TagFilter


async def main() -> None:
    async with RemembrClient(api_key="rk_demo") as client:
        session = await client.create_session(metadata={"topic": "transformers"})
        await client.store(
            "Need stronger evidence around inference cost tradeoffs.",
            role="assistant",
            session_id=session.session_id,
            tags=["agent:review", "topic:transformers", "kind:feedback", "confidence:0.6"],
        )
        feedback = await client.search(
            "How should research improve next time?",
            session_id=session.session_id,
            tag_filters=[TagFilter(key="kind", value="feedback")],
            search_mode="keyword",
        )
        print(feedback.total)


asyncio.run(main())
```

