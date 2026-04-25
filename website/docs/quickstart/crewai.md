# CrewAI Quickstart

## Install

```bash
pip install remembr crewai
```

## Initialize

```python
from remembr import RemembrClient
from adapters.crewai.remembr_crew_memory import RemembrCrewMemory

client = RemembrClient(api_key="rk_demo", base_url="http://localhost:8000/api/v1")
memory = RemembrCrewMemory(
    client=client,
    agent_id="researcher-1",
    agent_role="Researcher",
    team_id="go-to-market",
    short_term_session_id="crew-run-1",
)
```

## Store

```python
memory.save("Customer uses SAML and requires SCIM provisioning.")
```

## Search

```python
results = memory.search("What identity requirements did the customer mention?")
print(results)
```

## Delete

```python
memory.reset()
```

## Real sample

```python
from remembr import RemembrClient
from adapters.crewai.remembr_crew_memory import RemembrCrewMemory

client = RemembrClient(api_key="rk_demo", base_url="http://localhost:8000/api/v1")
crew_memory = RemembrCrewMemory(client=client, session_id="proposal-run")
crew_memory = RemembrCrewMemory(
    client=client,
    agent_id="writer-1",
    agent_role="Writer",
    team_id="proposal-team",
    short_term_session_id="proposal-run",
)

crew_memory.save("Draft should mention EU data residency.")

items = crew_memory.search("What should the proposal include?")
print(items)
```
