# Haystack Quickstart

## Install

--8<-- "_includes/install-haystack.md"

## Initialize

```python
from remembr import RemembrClient
from adapters.haystack.remembr_haystack_memory import RemembrMemoryRetriever, RemembrMemoryWriter

client = RemembrClient(api_key="rk_demo", base_url="http://localhost:8000/api/v1")
writer = RemembrMemoryWriter(client=client, default_session_id="haystack-run")
retriever = RemembrMemoryRetriever(client=client, default_session_id="haystack-run")
```

## Store

```python
writer.run(
    content="Keep the audit log for every destructive admin action.",
    role="assistant",
    tags=["kind:policy", "surface:admin-ui"],
)
```

## Search

```python
results = retriever.run(
    query="What policy applies to destructive admin actions?",
    search_mode="keyword",
)
print(results)
```

## Delete

```python
import asyncio


async def clear() -> None:
    await client.forget_session("haystack-run")


asyncio.run(clear())
```

## Real sample

```python
from remembr import RemembrClient
from adapters.haystack.remembr_haystack_memory import RemembrMemoryRetriever, RemembrMemoryWriter

client = RemembrClient(api_key="rk_demo", base_url="http://localhost:8000/api/v1")
writer = RemembrMemoryWriter(client=client, default_session_id="support-search")
retriever = RemembrMemoryRetriever(client=client, default_session_id="support-search")

writer.run(
    content="Enterprise customers need SSO and audit export before rollout.",
    role="user",
    tags=["kind:requirement", "segment:enterprise"],
)
print(
    retriever.run(
        query="What does enterprise need before rollout?",
        tag_filters=[{"key": "segment", "value": "enterprise"}],
    )
)
```
