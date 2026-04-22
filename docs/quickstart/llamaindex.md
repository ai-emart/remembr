# LlamaIndex Quickstart

## Install

--8<-- "_includes/install-llamaindex.md"

## Initialize

```python
from llama_index.core.base.llms.types import ChatMessage, MessageRole
from remembr import RemembrClient
from adapters.llamaindex.remembr_llamaindex_memory import RemembrChatStore

client = RemembrClient(api_key="rk_demo", base_url="http://localhost:8000/api/v1")
chat_store = RemembrChatStore(client=client)
```

## Store

```python
chat_store.add_message(
    "llama-session",
    ChatMessage(role=MessageRole.USER, content="The migration must preserve webhook delivery logs."),
)
```

## Search

```python
results = chat_store.get_messages("llama-session")
print(results)
```

## Delete

```python
chat_store.delete_messages("llama-session")
```

## Real sample

```python
from remembr import RemembrClient
from adapters.llamaindex.remembr_llamaindex_memory import RemembrSemanticMemory

client = RemembrClient(api_key="rk_demo", base_url="http://localhost:8000/api/v1")
store = RemembrSemanticMemory.from_client(client=client, session_id="index-session")

matches = store.load_context({"input": "What compatibility requirement do we have?"})
print(matches)
```
