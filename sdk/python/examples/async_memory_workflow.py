"""Async memory workflow example for the Remembr SDK."""

import asyncio

from remembr import RemembrClient


async def main() -> None:
    async with RemembrClient() as client:
        session = await client.create_session(metadata={"topic": "support-chat"})
        await client.store(
            content="Customer is interested in annual billing.",
            role="user",
            session_id=session.session_id,
            tags=["billing", "lead"],
        )

        result = await client.search(
            query="billing preference",
            session_id=session.session_id,
            search_mode="hybrid",
            weights={"semantic": 0.6, "keyword": 0.3, "recency": 0.1},
        )
        print(f"Found {result.total} result(s)")


if __name__ == "__main__":
    asyncio.run(main())
