from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

from adapters.base.tests.mock_remembr_sdk import MockRemembrAPI
from src.graph import GraphDependencies, run_topic
from src.memory import SessionRegistry, SharedLangGraphMemory


@dataclass
class SequenceLLM:
    responses: list[str]

    def __post_init__(self) -> None:
        self.prompts: list[str] = []
        self._index = 0

    def invoke(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self._index >= len(self.responses):
            raise AssertionError("No fake LLM response left for prompt")
        response = self.responses[self._index]
        self._index += 1
        return response


@dataclass
class FakeSearchTool:
    results: list[str]

    def __post_init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, max_results: int = 5) -> list[str]:
        self.queries.append(query)
        return self.results[:max_results]


def _memory_for(topic: str) -> tuple[SharedLangGraphMemory, MockRemembrAPI]:
    api = MockRemembrAPI()
    client = api.build_client()
    registry = SessionRegistry(path=_temp_registry_path(topic))
    memory = SharedLangGraphMemory.from_client(client=client, topic=topic, registry=registry)
    return memory, api


def _temp_registry_path(topic: str):
    safe = topic.lower().replace(" ", "-")
    return Path(mkdtemp(prefix=f"remembr-example-{safe}-")) / "sessions.json"


def test_all_three_agents_share_one_session_and_write_memories() -> None:
    topic = "Transformer dominance in 2026"
    memory, api = _memory_for(topic)
    llm = SequenceLLM(
        [
            '{"summary":"research","findings":["Transformers scale well","Ecosystem lock-in matters"]}',
            '{"draft":"Transformers remain dominant because they scale, have tooling, and fit multimodal work."}',
            '{"feedback":"Add stronger comparison against alternatives.","confidence":0.82,"needs_revision":false}',
        ]
    )
    deps = GraphDependencies(llm=llm, memory=memory, search_tool=FakeSearchTool(["Result A", "Result B"]))

    result = run_topic(topic, deps)
    active = [episode for episode in api.episodes.values() if not episode["deleted"]]

    assert result["session_id"] == memory.session_id
    assert {episode["session_id"] for episode in active} == {memory.session_id}
    assert any("agent:research" in episode["tags"] for episode in active)
    assert any("agent:writing" in episode["tags"] for episode in active)
    assert any("agent:review" in episode["tags"] for episode in active)


def test_review_loop_stops_after_max_loops() -> None:
    topic = "Loop control topic"
    memory, _ = _memory_for(topic)
    llm = SequenceLLM(
        [
            '{"summary":"r1","findings":["Finding 1"]}',
            '{"draft":"Draft 1"}',
            '{"feedback":"Needs revision 1","confidence":0.2,"needs_revision":true}',
            '{"summary":"r2","findings":["Finding 2"]}',
            '{"draft":"Draft 2"}',
            '{"feedback":"Needs revision 2","confidence":0.3,"needs_revision":true}',
            '{"summary":"r3","findings":["Finding 3"]}',
            '{"draft":"Draft 3"}',
            '{"feedback":"Needs revision 3","confidence":0.4,"needs_revision":true}',
        ]
    )
    deps = GraphDependencies(
        llm=llm,
        memory=memory,
        search_tool=FakeSearchTool(["Fresh result"]),
        max_loops=3,
    )

    result = run_topic(topic, deps)

    assert result["loop_count"] == 3
    assert result["review"]["confidence"] == 0.4


def test_feedback_from_first_run_guides_second_run_research_prompt() -> None:
    topic = "Feedback carryover topic"
    memory, _ = _memory_for(topic)
    search_tool = FakeSearchTool(["Original search result"])

    first_llm = SequenceLLM(
        [
            '{"summary":"research","findings":["First pass finding"]}',
            '{"draft":"First draft"}',
            '{"feedback":"Compare transformers with state-space models explicitly.","confidence":0.9,"needs_revision":false}',
        ]
    )
    run_topic(topic, GraphDependencies(llm=first_llm, memory=memory, search_tool=search_tool))

    second_llm = SequenceLLM(
        [
            '{"summary":"research 2","findings":["Second pass finding"]}',
            '{"draft":"Second draft"}',
            '{"feedback":"Looks good now.","confidence":0.95,"needs_revision":false}',
        ]
    )
    run_topic(topic, GraphDependencies(llm=second_llm, memory=memory, search_tool=search_tool))

    research_prompt = second_llm.prompts[0]
    assert "Compare transformers with state-space models explicitly." in research_prompt


def test_topic_registry_reuses_same_session_for_same_topic() -> None:
    topic = "Registry topic"
    api = MockRemembrAPI()
    client = api.build_client()
    registry = SessionRegistry(path=_temp_registry_path(topic))

    first = SharedLangGraphMemory.from_client(client=client, topic=topic, registry=registry)
    second = SharedLangGraphMemory.from_client(client=client, topic=topic, registry=registry)

    assert first.session_id == second.session_id
