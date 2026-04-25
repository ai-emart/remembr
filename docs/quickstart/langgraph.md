# LangGraph Quickstart

## Install

--8<-- "_includes/install-langgraph.md"

## Initialize

```python
from remembr import RemembrClient
from adapters.langgraph.remembr_langgraph_memory import RemembrLangGraphCheckpointer

client = RemembrClient(api_key="YOUR_API_KEY", base_url="http://localhost:8000/api/v1")
checkpointer = RemembrLangGraphCheckpointer(client=client, session_id="thread-42")
```

## Store

```python
checkpoint = checkpointer.put(
    config={"configurable": {"thread_id": "thread-42"}},
    checkpoint={"id": "cp-1", "channel_values": {"messages": ["research completed"]}},
    metadata={},
)
print(checkpoint)
```

## Search

```python
restored = checkpointer.get({"configurable": {"thread_id": "thread-42"}})
print(restored)
```

## Delete

```python
import asyncio


async def clear() -> None:
    await client.forget_session("thread-42")


asyncio.run(clear())
```

## Real sample

```python
from langgraph.graph import END, START, StateGraph
from remembr import RemembrClient
from adapters.langgraph.remembr_langgraph_memory import RemembrLangGraphCheckpointer


def step(state: dict) -> dict:
    state["messages"] = state.get("messages", []) + ["researched answer"]
    return state


builder = StateGraph(dict)
builder.add_node("step", step)
builder.add_edge(START, "step")
builder.add_edge("step", END)

client = RemembrClient(api_key="YOUR_API_KEY", base_url="http://localhost:8000/api/v1")
graph = builder.compile(
    checkpointer=RemembrLangGraphCheckpointer(client=client, session_id="thread-42")
)
result = graph.invoke({"messages": []}, config={"configurable": {"thread_id": "thread-42"}})
print(result)
```
