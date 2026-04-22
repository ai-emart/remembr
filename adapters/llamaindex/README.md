# Remembr LlamaIndex Adapter

Use `RemembrChatStore` for chat-history persistence and `RemembrMemoryBuffer` or `RemembrSemanticMemory` for retrieval-aware memory.

```python
from remembr import RemembrClient, TagFilter
from adapters.llamaindex.remembr_llamaindex_memory import RemembrMemoryBuffer

client = RemembrClient(api_key="...")
memory = RemembrMemoryBuffer(
    client=client,
    session_id="sess-123",
    search_mode="keyword",
    tag_filters=[TagFilter(key="topic", value="product")],
)
messages = memory.get(input="pricing")
```

Immediate retrieval after a write may miss a just-stored memory while its embedding is still pending.
