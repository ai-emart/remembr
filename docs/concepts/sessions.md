# Sessions

Sessions are the top-level container for a conversation, workflow run, or thread. They give Remembr a stable unit for short-term context, checkpointing, restore, history, and scoped search.

## What a session does

- Groups related episodes under one `session_id`
- Maintains the short-term working set used for context windows
- Supports checkpoint and restore for long-running workflows
- Provides a natural idempotency surface for orchestration frameworks

## Create a session

```python
import asyncio

from remembr import RemembrClient


async def main() -> None:
    async with RemembrClient(api_key="rk_demo") as client:
        session = await client.create_session(
            metadata={"thread": "customer-42", "channel": "support"}
        )
        print(session.session_id)


asyncio.run(main())
```

## When to create a new session

- One user conversation
- One background job
- One multi-agent pipeline execution
- One LangGraph thread

Reuse the same session when memory should stay connected. Start a new one when context should be isolated.

