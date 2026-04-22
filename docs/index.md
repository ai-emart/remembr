# Remembr

Remembr is persistent memory infrastructure for AI systems. It gives agents a clean `store -> search -> delete` loop, session-aware short-term context, scoped multi-tenant isolation, and a self-hosted stack that runs with Docker and Ollama by default.

## Who it is for

- Application developers building assistants, copilots, and internal tools that need memory without inventing a memory layer from scratch.
- Agent framework users working in LangChain, LangGraph, CrewAI, AutoGen, LlamaIndex, Pydantic AI, OpenAI Agents, or Haystack.
- Platform teams self-hosting AI infrastructure with clear security, auditability, and deletion controls.

## 60-second demo

```bash
docker-compose up -d
```

```python
import asyncio

from remembr import RemembrClient, TagFilter


async def main() -> None:
    async with RemembrClient(
        api_key="rk_demo",
        base_url="http://localhost:8000/api/v1",
    ) as client:
        session = await client.create_session(metadata={"app": "demo"})

        episode = await client.store(
            "Ada prefers weekly billing summaries on Fridays.",
            role="user",
            session_id=session.session_id,
            tags=["kind:preference", "customer:ada"],
        )
        print(episode.embedding_status)

        results = await client.search(
            "When should billing summaries be sent?",
            session_id=session.session_id,
            tag_filters=[TagFilter(key="kind", value="preference")],
            search_mode="hybrid",
        )
        print(results.results[0].content)


asyncio.run(main())
```

## Core ideas

- Sessions group a conversation or workflow run.
- Episodes are immutable memory entries.
- Search can be `semantic`, `keyword`, or `hybrid`.
- Embeddings are asynchronous, so freshly stored episodes may return `embedding_status="pending"` before they become searchable semantically.
- Deletes are soft by default so teams can restore by mistake window, audit, and purge later.

## Start here

- [Framework quickstarts](quickstart/langchain.md)
- [Concepts](concepts/sessions.md)
- [API reference](api-reference.md)
- [Docker deployment](deployment/docker.md)
- [LangGraph multi-agent cookbook](cookbook/multi-agent-shared-memory.md)

