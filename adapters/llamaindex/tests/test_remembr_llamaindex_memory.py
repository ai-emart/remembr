from __future__ import annotations

from remembr import TagFilter

from adapters.base.tests.mock_remembr_sdk import MockRemembrAPI
from adapters.llamaindex.remembr_llamaindex_memory import (
    ChatMessage,
    MessageRole,
    RemembrChatStore,
    RemembrMemoryBuffer,
    RemembrSemanticMemory,
)


def test_llamaindex_round_trip_keyword_and_delete() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    semantic = RemembrSemanticMemory.from_client(client, search_kwargs={"limit": 5, "search_mode": "keyword"})
    semantic.save_context({"input": "customer timezone is WAT"}, {"output": "saved"})

    result = semantic.load_context({"input": "timezone"})
    semantic._run(client.forget_session(semantic.session_id))

    assert result["results"]
    assert "timezone" in result["results"][0].content.lower()


def test_llamaindex_chat_store_and_buffer_use_current_search_mode() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    session_id = RemembrSemanticMemory.from_client(client).session_id
    store = RemembrChatStore(client)

    store.add_message(session_id, ChatMessage(role=MessageRole.USER, content="keyword retriever"))
    buffer = RemembrMemoryBuffer(client=client, session_id=session_id, search_mode="keyword", token_limit=10)
    messages = buffer.get(input="keyword")

    payload = api.payloads_for("POST", "/api/v1/memory/search")[-1]
    assert messages
    assert payload["search_mode"] == "keyword"


def test_llamaindex_structured_tag_filters_flow_through_retriever() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    semantic = RemembrSemanticMemory.from_client(client)
    semantic._store("ops handbook", role="user", tags=["topic:ops", "team:platform"])

    retriever = semantic.as_retriever(
        search_mode="keyword",
        tag_filters=[TagFilter(key="team", value="platform")],
    )
    docs = retriever.retrieve("handbook")

    payload = api.payloads_for("POST", "/api/v1/memory/search")[-1]
    assert len(docs) == 1
    assert payload["tag_filters"] == [{"key": "team", "op": "eq", "value": "platform"}]


def test_llamaindex_idempotent_store_round_trip() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    session_id = RemembrSemanticMemory.from_client(client).session_id

    client.request(
        "POST",
        "/memory",
        json={"content": "same note", "role": "user", "session_id": session_id},
        idempotency_key="llamaindex-1",
    )
    second = client.request(
        "POST",
        "/memory",
        json={"content": "same note", "role": "user", "session_id": session_id},
        idempotency_key="llamaindex-1",
    )

    assert second["episode_id"] == "ep-1"
    assert len(api.episodes) == 1
