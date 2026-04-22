# Remembr AutoGen Adapter

`RemembrAutoGenMemory` hooks into AutoGen send and receive flows, and `RemembrAutoGenGroupChatMemory` keeps speaker-scoped group chat history.

```python
from remembr import RemembrClient
from adapters.autogen.remembr_autogen_memory import RemembrAutoGenMemory

client = RemembrClient(api_key="...")
memory = RemembrAutoGenMemory(client=client, session_id="sess-123")
memory.save_context(
    {"message": "Customer account is enterprise", "conversation_id": "conv-1", "message_index": 0},
    {"message": "Stored", "conversation_id": "conv-1", "message_index": 1},
)
```

Hook-based writes use `idempotency_key=f"autogen-{conversation_id}-{message_index}"`.
