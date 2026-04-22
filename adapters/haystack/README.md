# Remembr Haystack Adapter

Use `RemembrMemoryRetriever` and `RemembrMemoryWriter` inside Haystack pipelines, or `RemembrConversationMemory` for chat-style state.

```python
from remembr import RemembrClient, TagFilter
from adapters.haystack.remembr_haystack_memory import RemembrMemoryRetriever

client = RemembrClient(api_key="...")
retriever = RemembrMemoryRetriever(client=client, default_session_id="sess-123")
result = retriever.run(
    query="incident",
    search_mode="keyword",
    tag_filters=[TagFilter(key="team", value="platform")],
)
```

Retriever inputs now accept both `search_mode` and `tag_filters`.
