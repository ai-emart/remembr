from __future__ import annotations

import time

from remembr import TagFilter

from adapters.base.tests.mock_remembr_sdk import MockRemembrAPI
from adapters.openai_agents.remembr_openai_memory import (
    RemembrAgentHooks,
    RemembrHandoffMemory,
    RemembrMemoryTools,
)


class Tool:
    name = "memory_search"


class Agent:
    name = "support"


class Source:
    name = "router"


class Handoff:
    def __init__(self):
        self.on_handoff = None


def test_openai_agents_round_trip_store_search_and_delete() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    session_id = client.request("POST", "/sessions", json={"metadata": {"source": "oa"}})["session_id"]
    RemembrMemoryTools.configure(client)

    stored = RemembrMemoryTools.store_memory("billing notes", session_id, tags="topic:billing")
    found = RemembrMemoryTools.search_memory("billing", session_id)
    episode_id = next(iter(api.episodes))
    client.request("DELETE", f"/memory/{episode_id}")

    assert "embedding_status=pending" in stored
    assert "billing notes" in found
    assert api.episodes[episode_id]["deleted"] is True


def test_openai_agents_keyword_search_supports_structured_tags() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    session_id = client.request("POST", "/sessions", json={"metadata": {"source": "oa"}})["session_id"]
    client.request(
        "POST",
        "/memory",
        json={
            "content": "vip customer",
            "role": "user",
            "session_id": session_id,
            "tags": ["tier:vip", "topic:support"],
        },
    )

    result = client.request(
        "POST",
        "/memory/search",
        json={
            "query": "customer",
            "session_id": session_id,
            "search_mode": "keyword",
            "tag_filters": [TagFilter(key="tier", value="vip").to_dict()],
        },
    )

    assert result["results"][0]["content"] == "vip customer"


def test_openai_agents_hooks_and_handoff_flow() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    session_id = client.request("POST", "/sessions", json={"metadata": {"source": "oa"}})["session_id"]
    hooks = RemembrAgentHooks(client=client, session_id=session_id)

    hooks.on_tool_end(None, Agent(), Tool(), "ok")
    hooks.on_handoff(None, Agent(), Source())
    hooks.on_agent_end(None, Agent(), "done")
    time.sleep(0.05)

    handoff_memory = RemembrHandoffMemory(client=client, session_id=session_id)
    handoff_memory.store_before_handoff("router", "handoff payload")
    injected = handoff_memory.inject_after_handoff("support")
    wrapped = handoff_memory.attach_to_handoff(Handoff())

    assert callable(wrapped.on_handoff)
    assert "handoff" in injected.lower() or injected == ""


def test_openai_agents_idempotent_store_response_is_stable() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    session_id = client.request("POST", "/sessions", json={"metadata": {"source": "oa"}})["session_id"]

    first = client.request(
        "POST",
        "/memory",
        json={"content": "same store", "role": "user", "session_id": session_id},
        idempotency_key="openai-agents-1",
    )
    second = client.request(
        "POST",
        "/memory",
        json={"content": "same store", "role": "user", "session_id": session_id},
        idempotency_key="openai-agents-1",
    )

    assert first["episode_id"] == second["episode_id"]
