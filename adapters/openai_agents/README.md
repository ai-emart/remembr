# Remembr OpenAI Agents Adapter

The OpenAI Agents adapter exposes Remembr as function tools and lifecycle hooks.

```python
from remembr import RemembrClient
from adapters.openai_agents.remembr_openai_memory import RemembrMemoryTools

client = RemembrClient(api_key="...")
RemembrMemoryTools.configure(client)

summary = RemembrMemoryTools.search_memory("billing", "sess-123")
stored = RemembrMemoryTools.store_memory("VIP customer", "sess-123", tags="tier:vip,topic:support")
```

The store tool returns the SDK episode identifier and `embedding_status`.
