# Pydantic AI Quickstart

## Install

```bash
pip install remembr pydantic-ai
```

## Initialize

```python
from adapters.pydantic_ai.remembr_pydantic_memory import create_remembr_agent

agent = create_remembr_agent(
    model="openai:gpt-4o-mini",
    system_prompt="You are a helpful assistant.",
    api_key="YOUR_API_KEY",
    session_id="pydantic-run",
)
```

## Store

```python
print(agent.remembr_deps.session_id)
```

## Search

```python
print(agent.tools)
```

## Delete

```python
agent.remembr_deps.auto_store = False
```

## Real sample

```python
from adapters.pydantic_ai.remembr_pydantic_memory import create_remembr_agent

agent = create_remembr_agent(
    model="openai:gpt-4o-mini",
    system_prompt="You help sales engineers remember customer requirements.",
    api_key="YOUR_API_KEY",
    session_id="run-88",
)
print(agent.remembr_deps.session_id)
```
