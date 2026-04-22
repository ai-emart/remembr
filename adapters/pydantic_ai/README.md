# Remembr Pydantic AI Adapter

The Pydantic AI adapter uses dependency injection with the current SDK client and typed Remembr tools.

```python
from remembr import RemembrClient
from adapters.pydantic_ai.remembr_pydantic_memory import RemembrMemoryDep

client = RemembrClient(api_key="...")
deps = RemembrMemoryDep(
    client=client,
    session_id="sess-123",
    search_mode="keyword",
)
```

If the Pydantic AI run context exposes `run_id`, `request_id`, or `conversation_id`, that value is passed through as the Remembr `idempotency_key`.
