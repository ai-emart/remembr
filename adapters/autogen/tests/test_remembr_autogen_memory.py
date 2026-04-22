from __future__ import annotations

from remembr import TagFilter

from adapters.autogen.remembr_autogen_memory import RemembrAutoGenGroupChatMemory, RemembrAutoGenMemory
from adapters.base.tests.mock_remembr_sdk import MockRemembrAPI


class FakeAgent:
    def __init__(self, name: str):
        self.name = name
        self.hooks: dict[str, callable] = {}

    def register_hook(self, hook_name: str, fn):
        self.hooks[hook_name] = fn


class FakeGroupChat:
    def __init__(self):
        self.messages = []

    def append(self, message, speaker=None):
        self.messages.append((speaker.name if speaker else "unknown", message))


class Speaker:
    def __init__(self, name: str):
        self.name = name


def test_autogen_round_trip_keyword_and_delete() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    memory = RemembrAutoGenMemory(client=client)

    memory.save_context({"message": "customer prefers async code"}, {"message": "understood"})
    context = memory.get_relevant_context("async")
    memory._run(client.forget_session(memory.session_id))

    assert "async" in context.lower()
    assert not [
        episode
        for episode in api.episodes.values()
        if episode["session_id"] == memory.session_id and not episode["deleted"]
    ]


def test_autogen_hook_idempotency_uses_conversation_and_message_index() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    memory = RemembrAutoGenMemory(client=client)
    agent = FakeAgent("coder")
    memory.attach_to_agent(agent)

    agent.hooks["process_message_after_receive"](
        "hello",
        conversation_id="conv-1",
        message_index=4,
    )
    agent.hooks["process_message_after_receive"](
        "hello",
        conversation_id="conv-1",
        message_index=4,
    )

    headers = api.headers_for("POST", "/api/v1/memory")
    active = [episode for episode in api.episodes.values() if not episode["deleted"]]
    assert len(active) == 1
    assert headers[0]["Idempotency-Key"] == "autogen-conv-1-4"


def test_autogen_keyword_search_with_structured_tags() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    memory = RemembrAutoGenMemory(client=client)

    memory._store("review the parser edge cases", role="user", tags=["topic:testing", "agent:reviewer"])
    result = memory._search(
        query="parser",
        search_mode="keyword",
        tag_filters=[TagFilter(key="agent", value="reviewer")],
    )

    payload = api.payloads_for("POST", "/api/v1/memory/search")[-1]
    assert len(result.results) == 1
    assert payload["search_mode"] == "keyword"


def test_autogen_group_chat_memory_filters_by_speaker() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    memory = RemembrAutoGenGroupChatMemory(client=client)
    group_chat = FakeGroupChat()
    memory.attach_to_group_chat(group_chat)

    group_chat.append("Use stricter tests", speaker=Speaker("Reviewer"))
    group_chat.append("Added keyword coverage", speaker=Speaker("Coder"))

    reviewer_context = memory.query_agent_memory("Reviewer", "stricter")
    assert "Reviewer" in reviewer_context
