from __future__ import annotations

from types import SimpleNamespace

from remembr import TagFilter

from adapters.base.tests.mock_remembr_sdk import MockRemembrAPI
from adapters.pydantic_ai.remembr_pydantic_memory import (
    RemembrMemoryDep,
    RemembrMemoryTools,
    RunContext,
    remembr_system_prompt,
)


def test_pydantic_ai_round_trip_store_search_forget() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    session_id = client.request("POST", "/sessions", json={"metadata": {"source": "test"}})["session_id"]
    dep = RemembrMemoryDep(client=client, session_id=session_id, search_mode="keyword")
    ctx = RunContext(deps=dep)

    stored = RemembrMemoryTools.store_memory(ctx, "user likes tags", tags=["topic:pydantic"])
    found = RemembrMemoryTools.search_memory(ctx, "tags")
    episode_id = next(iter(api.episodes))
    forgotten = RemembrMemoryTools.forget_memory(ctx, episode_id)

    assert "embedding_status=pending" in stored
    assert "Relevant memories:" in found
    assert episode_id in forgotten


def test_pydantic_ai_store_uses_run_context_idempotency() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    session_id = client.request("POST", "/sessions", json={"metadata": {"source": "test"}})["session_id"]
    dep = RemembrMemoryDep(client=client, session_id=session_id)
    ctx = RunContext(deps=dep)
    ctx.run_id = "run-123"  # type: ignore[attr-defined]

    RemembrMemoryTools.store_memory(ctx, "repeat me")
    RemembrMemoryTools.store_memory(ctx, "repeat me")

    headers = api.headers_for("POST", "/api/v1/memory")
    assert headers[0]["Idempotency-Key"] == "run-123"
    assert len(api.episodes) == 1


def test_pydantic_ai_keyword_search_and_tag_filters() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    session_id = client.request("POST", "/sessions", json={"metadata": {"source": "test"}})["session_id"]
    dep = RemembrMemoryDep(client=client, session_id=session_id, search_mode="keyword")

    client.request(
        "POST",
        "/memory",
        json={
            "content": "platform note",
            "role": "user",
            "session_id": session_id,
            "tags": ["topic:ops", "team:platform"],
        },
    )
    result = client.request(
        "POST",
        "/memory/search",
        json={
            "query": "platform",
            "session_id": session_id,
            "search_mode": "keyword",
            "tag_filters": [TagFilter(key="team", value="platform").to_dict()],
        },
    )

    prompt = remembr_system_prompt(SimpleNamespace(deps=dep))
    assert result["results"][0]["content"] == "platform note"
    assert "prior memories" in prompt.lower() or "user" in prompt.lower()
