from __future__ import annotations

import sys
import types

from remembr import TagFilter

from adapters.base.tests.mock_remembr_sdk import MockRemembrAPI


if "langchain_core.memory" not in sys.modules:
    memory = types.ModuleType("langchain_core.memory")

    class BaseMemory:  # pragma: no cover - shim
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    memory.BaseMemory = BaseMemory
    sys.modules["langchain_core.memory"] = memory

if "langchain_core.messages" not in sys.modules:
    messages = types.ModuleType("langchain_core.messages")

    class _Message:  # pragma: no cover - shim
        def __init__(self, content: str):
            self.content = content

    class HumanMessage(_Message):
        type = "human"

    class AIMessage(_Message):
        type = "ai"

    messages.HumanMessage = HumanMessage
    messages.AIMessage = AIMessage
    sys.modules["langchain_core.messages"] = messages

from adapters.langchain.remembr_memory import RemembrMemory
from langchain_core.messages import AIMessage, HumanMessage


def test_langchain_round_trip_keyword_and_clear() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    memory = RemembrMemory(client=client, search_mode="keyword")

    memory.save_context({"input": "customer prefers python"}, {"output": "noted"})
    loaded = memory.load_memory_variables({"input": "python"})
    memory.clear()

    assert loaded["history"]
    assert loaded["history"][0].content == "customer prefers python"
    assert not [
        episode
        for episode in api.episodes.values()
        if episode["session_id"] == memory.session_id and not episode["deleted"]
    ]


def test_langchain_write_idempotency_uses_session_hash_key() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    memory = RemembrMemory(client=client)

    message = HumanMessage(content="same turn")
    memory.add_messages([message])
    memory.add_messages([message])

    active = [episode for episode in api.episodes.values() if not episode["deleted"]]
    headers = api.headers_for("POST", "/api/v1/memory")

    assert len(active) == 1
    assert headers[0]["Idempotency-Key"] == headers[1]["Idempotency-Key"]
    assert headers[0]["Idempotency-Key"].startswith(f"langchain-{memory.session_id}-")


def test_langchain_structured_tag_filters_with_keyword_search() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    memory = RemembrMemory(client=client, search_mode="keyword")

    memory._store("python memory", role="user", tags=["topic:python", "scope:langchain"])
    memory._store("golang memory", role="user", tags=["topic:go", "scope:langchain"])

    messages = memory.get_messages(
        query="python",
        search_mode="keyword",
        tag_filters=[TagFilter(key="topic", value="python")],
    )

    payload = api.payloads_for("POST", "/api/v1/memory/search")[-1]
    assert len(messages) == 1
    assert messages[0].content == "python memory"
    assert payload["search_mode"] == "keyword"
    assert payload["tag_filters"] == [{"key": "topic", "op": "eq", "value": "python"}]


def test_langchain_get_messages_without_query_returns_history() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    memory = RemembrMemory(client=client)

    memory.add_messages([HumanMessage(content="hello"), AIMessage(content="hi")])

    messages = memory.get_messages()
    assert [message.content for message in messages] == ["hello", "hi"]
