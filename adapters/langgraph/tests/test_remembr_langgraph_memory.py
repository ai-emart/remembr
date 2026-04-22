from __future__ import annotations

from remembr import TagFilter

from adapters.base.tests.mock_remembr_sdk import MockRemembrAPI
from adapters.langgraph.remembr_langgraph_memory import (
    RemembrLangGraphCheckpointer,
    RemembrLangGraphMemory,
    add_remembr_to_graph,
)


class FakeGraph:
    def __init__(self):
        self.nodes = {"agent": lambda s, c: s}
        self.edges = [("agent", "__end__")]

    def add_node(self, name, fn):
        self.nodes[name] = fn

    def add_edge(self, src, dst):
        self.edges.append((src, dst))


def test_langgraph_round_trip_search_and_delete() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    memory = RemembrLangGraphMemory(client=client, search_mode="keyword")
    state = {"messages": [{"role": "user", "content": "project codename atlas"}]}

    memory.save_memories(state, {"configurable": {"thread_id": "thread-1"}})
    loaded = memory.load_memories(state, {"configurable": {"thread_id": "thread-1"}})
    memory._run(client.forget_session(memory.session_id))

    assert "atlas" in loaded["remembr_context"].lower()
    assert not [
        episode
        for episode in api.episodes.values()
        if episode["session_id"] == memory.session_id and not episode["deleted"]
    ]


def test_langgraph_keyword_search_with_structured_tags() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    memory = RemembrLangGraphMemory(client=client, search_mode="keyword")

    memory._store("thread specific note", role="user", tags=["topic:ops", "thread:t-1"])
    result = memory._search(
        query="specific",
        search_mode="keyword",
        tag_filters=[TagFilter(key="thread", value="t-1")],
    )

    payload = api.payloads_for("POST", "/api/v1/memory/search")[-1]
    assert len(result.results) == 1
    assert payload["search_mode"] == "keyword"


def test_langgraph_checkpointer_uses_checkpoint_api_and_idempotency() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    checkpointer = RemembrLangGraphCheckpointer(client=client)
    config = {"configurable": {"thread_id": "thread-9"}}

    checkpointer.put(config, {"id": "cp-a", "state": "draft"}, {"stage": 1})
    checkpointer.put(config, {"id": "cp-a", "state": "draft"}, {"stage": 1})
    restored = checkpointer.restore_checkpoint(config)

    checkpoints = api.payloads_for("POST", f"/api/v1/sessions/{checkpointer.session_id}/restore")
    headers = api.headers_for("POST", f"/api/v1/sessions/{checkpointer.session_id}/checkpoint")
    listed = checkpointer._run(client.list_checkpoints(checkpointer.session_id))

    assert restored["restored"] is True
    assert len(listed) == 1
    assert headers[0]["Idempotency-Key"] == "lg-thread-9-cp-a"
    assert checkpoints[-1]["checkpoint_id"] == listed[0].checkpoint_id


def test_langgraph_graph_wiring_adds_memory_nodes() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    graph = FakeGraph()

    out = add_remembr_to_graph(graph, client=client)

    assert out is graph
    assert "remembr_load_memories" in graph.nodes
    assert "remembr_save_memories" in graph.nodes
