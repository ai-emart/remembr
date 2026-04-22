from __future__ import annotations

from remembr import TagFilter

from adapters.base.tests.mock_remembr_sdk import MockRemembrAPI
from adapters.haystack.remembr_haystack_memory import (
    RemembrConversationMemory,
    RemembrMemoryRetriever,
    RemembrMemoryWriter,
)


class Msg:
    def __init__(self, role: str, text: str):
        self.role = role
        self.text = text


def test_haystack_round_trip_writer_retriever_and_delete() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    session_id = client.request("POST", "/sessions", json={"metadata": {"source": "hay"}})["session_id"]
    writer = RemembrMemoryWriter(client=client, default_session_id=session_id)
    retriever = RemembrMemoryRetriever(client=client, default_session_id=session_id)

    stored = writer.run(content="haystack keyword search", tags=["topic:haystack"])
    found = retriever.run(query="keyword", search_mode="keyword")
    client.request("DELETE", f"/memory/{stored['episode_id']}")

    assert stored["stored"] is True
    assert found["memories"]
    assert api.episodes[stored["episode_id"]]["deleted"] is True


def test_haystack_keyword_search_and_tag_filters_inputs() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    session_id = client.request("POST", "/sessions", json={"metadata": {"source": "hay"}})["session_id"]
    writer = RemembrMemoryWriter(client=client, default_session_id=session_id)
    retriever = RemembrMemoryRetriever(client=client, default_session_id=session_id)

    writer.run(content="platform runbook", tags=["topic:ops", "team:platform"])
    result = retriever.run(
        query="runbook",
        search_mode="keyword",
        tag_filters=[TagFilter(key="team", value="platform")],
    )

    payload = api.payloads_for("POST", "/api/v1/memory/search")[-1]
    assert result["memories"]
    assert payload["search_mode"] == "keyword"
    assert payload["tag_filters"] == [{"key": "team", "op": "eq", "value": "platform"}]


def test_haystack_conversation_memory_end_to_end() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    session_id = client.request("POST", "/sessions", json={"metadata": {"source": "hay"}})["session_id"]
    memory = RemembrConversationMemory(
        client=client,
        session_id=session_id,
        retrieval_query="support",
        search_mode="keyword",
    )

    memory.write_messages([Msg("user", "support queue"), Msg("assistant", "support response")])
    retrieved = memory.retrieve(limit=5)
    memory.delete_messages(list(api.episodes.keys()))

    assert len(retrieved) >= 1


def test_haystack_idempotent_store_reuses_episode() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    session_id = client.request("POST", "/sessions", json={"metadata": {"source": "hay"}})["session_id"]

    first = client.request(
        "POST",
        "/memory",
        json={"content": "same haystack fact", "role": "user", "session_id": session_id},
        idempotency_key="hay-1",
    )
    second = client.request(
        "POST",
        "/memory",
        json={"content": "same haystack fact", "role": "user", "session_id": session_id},
        idempotency_key="hay-1",
    )

    assert first["episode_id"] == second["episode_id"]
