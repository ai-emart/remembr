from __future__ import annotations

from remembr import TagFilter

from adapters.base.tests.mock_remembr_sdk import MockRemembrAPI
from adapters.crewai.remembr_crew_memory import RemembrCrewMemory, RemembrSharedCrewMemory


def test_crewai_round_trip_search_and_reset() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    memory = RemembrCrewMemory(client=client, agent_id="researcher", agent_role="Researcher", team_id="team-1")

    memory.save("customer likes summaries")
    matches = memory.search("summaries")
    memory.reset()

    assert matches
    assert matches[0].content == "customer likes summaries"
    assert not [
        episode
        for episode in api.episodes.values()
        if episode["session_id"] == memory.short_term and not episode["deleted"]
    ]


def test_crewai_idempotent_sdk_write_reuses_response() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    session = client.request("POST", "/sessions", json={"metadata": {"name": "crew"}})["session_id"]

    first = client.request(
        "POST",
        "/memory",
        json={"content": "shared fact", "role": "user", "session_id": session},
        idempotency_key="crew-static-key",
    )
    second = client.request(
        "POST",
        "/memory",
        json={"content": "shared fact", "role": "user", "session_id": session},
        idempotency_key="crew-static-key",
    )

    assert first["episode_id"] == second["episode_id"]
    assert len(api.episodes) == 1


def test_crewai_tag_filters_and_keyword_search() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    memory = RemembrCrewMemory(client=client, agent_id="planner", agent_role="Planner", team_id="team-2")

    memory.save("plan sprint backlog")
    results = memory._run(
        client.search(
            query="plan",
            session_id=memory.long_term,
            search_mode="keyword",
            tag_filters=[TagFilter(key="agent", value="Planner")],
        )
    )

    payload = api.payloads_for("POST", "/api/v1/memory/search")[-1]
    assert len(results.results) == 1
    assert payload["search_mode"] == "keyword"


def test_crewai_shared_memory_injects_agent_specific_tags() -> None:
    api = MockRemembrAPI()
    client = api.build_client()
    shared = RemembrSharedCrewMemory(client=client, team_id="crew-77")

    class Agent:
        def __init__(self, role: str):
            self.role = role
            self.memory = None

    class Crew:
        def __init__(self):
            self.agents = [Agent("Researcher"), Agent("Writer")]

    crew = Crew()
    shared.inject_into_crew(crew)
    crew.agents[0].memory.save("Mercury is closest to the sun")

    stored = [episode for episode in api.episodes.values() if not episode["deleted"]]
    assert any("agent:Researcher" in episode["tags"] for episode in stored)
