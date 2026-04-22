# Remembr

Remembr gives AI systems durable, searchable memory with clear session boundaries, scoped multi-tenant isolation, and a Docker-first self-hosted stack. It is built for agents that need `store`, `search`, and `delete` without inventing a memory backend from scratch.

## The three calls

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
            content="User prefers Friday billing summaries.",
            role="user",
            session_id=session.session_id,
            tags=["kind:preference", "topic:billing"],
        )
        print(episode.embedding_status)

        results = await client.search(
            query="When should summaries be sent?",
            session_id=session.session_id,
            tag_filters=[TagFilter(key="kind", value="preference")],
            search_mode="hybrid",
        )
        print(results.results[0].content)

        await client.forget_session(session.session_id)


asyncio.run(main())
```

## Run it

```bash
docker-compose up -d
docker-compose exec server alembic upgrade head
curl http://localhost:8000/health
```

## Read the docs

- Docs: [`docs/index.md`](docs/index.md)
- Framework quickstarts: [`docs/quickstart/langchain.md`](docs/quickstart/langchain.md)
- API reference: [`docs/api-reference.md`](docs/api-reference.md)
- Self-hosting: [`docs/self-hosted.md`](docs/self-hosted.md)
- Discord: `https://discord.gg/remembr-placeholder`
- GitHub Sponsors: `https://github.com/sponsors/ai-emart`

