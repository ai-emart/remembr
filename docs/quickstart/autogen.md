# AutoGen Quickstart

## Install

--8<-- "_includes/install-autogen.md"

## Initialize

```python
from remembr import RemembrClient
from adapters.autogen.remembr_autogen_memory import RemembrAutoGenMemory

client = RemembrClient(api_key="YOUR_API_KEY", base_url="http://localhost:8000/api/v1")
memory = RemembrAutoGenMemory(client=client, conversation_id="conv-7")
```

## Store

```python
memory.save_context(
    {"message": "Investigate repeated 401s on the staging API.", "conversation_id": "conv-7", "message_index": 0},
    {"message": "I will investigate the repeated 401s."},
)
```

## Search

```python
hits = memory.load_context({"message": "What issue are we debugging?"})
print(hits)
```

## Delete

```python
import asyncio


async def clear() -> None:
    await client.forget_session(memory.session_id)


asyncio.run(clear())
```

## Real sample

```python
from remembr import RemembrClient
from adapters.autogen.remembr_autogen_memory import RemembrAutoGenMemory

client = RemembrClient(api_key="YOUR_API_KEY", base_url="http://localhost:8000/api/v1")
conversation = RemembrAutoGenMemory(client=client, conversation_id="conv-support")

conversation.save_context(
    {"message": "Why did staging return 401?", "conversation_id": "conv-support", "message_index": 1},
    {"message": "The root cause was an expired staging OAuth client secret."},
)

print(conversation.get_relevant_context("What caused the 401s?"))
```
