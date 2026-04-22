# Remembr CrewAI Adapter

`RemembrCrewMemory` keeps short-term and long-term memory aligned while tagging writes with the agent role.

```python
from remembr import RemembrClient, TagFilter
from adapters.crewai.remembr_crew_memory import RemembrCrewMemory

client = RemembrClient(api_key="...")
memory = RemembrCrewMemory(
    client=client,
    agent_id="researcher-1",
    agent_role="Researcher",
    team_id="crew-alpha",
)

memory.save("Vendor prefers weekly status updates")
results = client.request(
    "POST",
    "/memory/search",
    json={
        "query": "vendor",
        "session_id": memory.long_term,
        "search_mode": "keyword",
        "tag_filters": [TagFilter(key="agent", value="Researcher").to_dict()],
    },
)
```

Every write includes `tags=[f"agent:{agent.role}"]`.
