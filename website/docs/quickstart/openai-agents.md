# OpenAI Agents Quickstart

## Install

```bash
pip install remembr openai-agents
```

## Initialize

```python
from remembr import RemembrClient
from adapters.openai_agents.remembr_openai_memory import RemembrMemoryTools

client = RemembrClient(api_key="rk_demo", base_url="http://localhost:8000/api/v1")
RemembrMemoryTools.configure(client)
```

## Store

```python
result = RemembrMemoryTools.store_memory(
    content="Reviewer asked for stronger evidence on rollback safety.",
    session_id="agents-session",
    tags="kind:feedback,topic:deployments",
)
print(result)
```

## Search

```python
print(
    RemembrMemoryTools.search_memory(
        query="What feedback did the reviewer leave?",
        session_id="agents-session",
    )
)
```

## Delete

```python
import asyncio


async def clear() -> None:
    await client.forget_session("agents-session")


asyncio.run(clear())
```

## Real sample

```python
from remembr import RemembrClient
from adapters.openai_agents.remembr_openai_memory import RemembrMemoryTools

client = RemembrClient(api_key="rk_demo", base_url="http://localhost:8000/api/v1")
RemembrMemoryTools.configure(client)

print(
    RemembrMemoryTools.store_memory(
        content="Cite the benchmark regression fix in the release note.",
        session_id="writer-agent",
        tags="kind:todo,release:1.0",
    )
)
print(RemembrMemoryTools.search_memory(query="What belongs in the release note?", session_id="writer-agent"))
```
