# LangChain Quickstart

## Install

```bash
pip install remembr langchain langchain-openai
```

## Initialize

```python
from langchain_core.messages import AIMessage, HumanMessage
from remembr import RemembrClient
from adapters.langchain.remembr_memory import RemembrMemory

client = RemembrClient(api_key="YOUR_API_KEY", base_url="http://localhost:8000/api/v1")
memory = RemembrMemory(
    client=client,
    session_id="support-session-1",
    search_mode="hybrid",
)
```

## Store

```python
memory.add_messages(
    [
        HumanMessage(content="Customer wants invoices every Friday."),
        AIMessage(content="I will remember the Friday billing preference."),
    ]
)
```

## Search

```python
context = memory.load_context({"input": "When should we send invoices?"})
print(context)
```

## Delete

```python
memory.clear()
```

## End-to-end sample

```python
from langchain_core.messages import AIMessage, HumanMessage
from remembr import RemembrClient
from adapters.langchain.remembr_memory import RemembrMemory

client = RemembrClient(api_key="YOUR_API_KEY", base_url="http://localhost:8000/api/v1")
history = RemembrMemory(
    client=client,
    session_id="lc-session",
    search_mode="keyword",
)

history.add_messages(
    [
        HumanMessage(content="Order 1842 was delayed by customs."),
        AIMessage(content="Logged the shipping issue for follow-up."),
    ]
)

matches = history.get_messages(query="Which order hit customs?")
print(matches)
```

Note: writes return immediately, and `embedding_status="pending"` means a same-turn semantic search may not include the newest memory yet.
