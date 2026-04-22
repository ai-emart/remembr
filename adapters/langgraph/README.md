# Remembr LangGraph Adapter

`RemembrLangGraphMemory` adds retrieval nodes around a graph, and `RemembrLangGraphCheckpointer` uses the SDK checkpoint and restore APIs.

```python
from remembr import RemembrClient
from adapters.langgraph.remembr_langgraph_memory import (
    RemembrLangGraphCheckpointer,
    RemembrLangGraphMemory,
)

client = RemembrClient(api_key="...")
memory = RemembrLangGraphMemory(client=client, session_id="sess-123")
checkpointer = RemembrLangGraphCheckpointer(client=client, session_id="sess-123")

# Three-agent pattern: planner -> researcher -> writer
# See examples/langgraph-multi-agent/ for a fuller layout.
state = {"messages": [{"role": "user", "content": "Plan the launch"}]}
state = memory.load_memories(state, {"configurable": {"thread_id": "thread-1"}})
checkpointer.put({"configurable": {"thread_id": "thread-1"}}, {"id": "cp-1"}, {"agent": "planner"})
```

Checkpoint writes use `idempotency_key=f"lg-{thread_id}-{checkpoint_id}"`.
