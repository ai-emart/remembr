# Remembr LangChain Adapter

`RemembrMemory` wraps the current Python SDK and exposes LangChain-friendly memory methods like `save_context`, `get_messages`, and `clear`.

```python
from remembr import RemembrClient, TagFilter
from adapters.langchain.remembr_memory import RemembrMemory

client = RemembrClient(api_key="...")
memory = RemembrMemory(client=client, session_id="sess-123", search_mode="hybrid")

memory.save_context({"input": "Customer prefers email"}, {"output": "Saved"})
messages = memory.get_messages(
    query="customer",
    tag_filters=[TagFilter(key="topic", value="support")],
)
```

Writes use `idempotency_key=f"langchain-{session_id}-{message_hash}"`.

Newly stored memories may return `embedding_status="pending"`, so immediate search may not include them yet.
