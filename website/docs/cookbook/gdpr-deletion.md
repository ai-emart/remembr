# GDPR Deletion

V1 gives you the building blocks for data deletion workflows even though it is not a full policy engine.

## Typical flow

1. Identify the user and relevant sessions.
2. Export their data for review.
3. Soft-delete user memory with `DELETE /memory/user/{user_id}`.
4. Restore if the deletion request was a mistake during the grace period.
5. Hard-delete specific records when permanent purge is required.

## Example

```python
import asyncio

from remembr import RemembrClient


async def main() -> None:
    async with RemembrClient(api_key="YOUR_API_KEY") as client:
        report = await client.forget_user("00000000-0000-0000-0000-000000000000")
        print(report)


asyncio.run(main())
```

