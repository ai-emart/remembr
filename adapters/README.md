# Remembr Framework Adapters

## Comparison

| Adapter | Framework | Idempotency | Tag Filters | Search Modes | Webhooks |
|---|---|---|---|---|---|
| `langchain` | LangChain | ✅ | ✅ | ✅ | ❌ |
| `langgraph` | LangGraph | ✅ | ✅ | ✅ | ❌ |
| `crewai` | CrewAI | ✅ | ✅ | ✅ | ❌ |
| `autogen` | AutoGen | ✅ | ✅ | ✅ | ❌ |
| `llamaindex` | LlamaIndex | ✅ | ✅ | ✅ | ❌ |
| `pydantic_ai` | Pydantic AI | ✅ | ✅ | ✅ | ❌ |
| `openai_agents` | OpenAI Agents SDK | ✅ | ✅ | ✅ | ❌ |
| `haystack` | Haystack | ✅ | ✅ | ✅ | ❌ |

## Install

- `pip install remembr-langchain-adapter`
- `pip install remembr-langgraph-adapter`
- `pip install remembr-crewai-adapter`
- `pip install remembr-autogen-adapter`
- `pip install remembr-llamaindex-adapter`
- `pip install remembr-pydantic-ai-adapter`
- `pip install remembr-openai-agents-adapter`
- `pip install remembr-haystack-adapter`

## When to use each

- **LangChain**: You already use memory abstractions like `ConversationBufferMemory`.
- **LangGraph**: You want durable graph state and explicit checkpoint/restore integration.
- **CrewAI**: You need short-term private plus long-term shared crew memory.
- **AutoGen**: You want message-hook based contextual injection.
- **LlamaIndex**: You need retriever-aware memory inside chat/query engines.
- **Pydantic AI**: You prefer typed deps, typed tools, and prompt composition.
- **OpenAI Agents SDK**: You need tools, hooks, and handoff memory.
- **Haystack**: You build component pipelines and want memory as reusable nodes.

## Common patterns and gotchas

- All adapters wrap the Python SDK in `sdk/python/remembr`; none call the REST API directly.
- Store responses can return `embedding_status="pending"`. Immediate search after write may not include the new memory yet.
- Role normalization is handled centrally via `parse_role(...)`.
- Prefer explicit `session_id` values for continuity across runs and replay.
- Structured tags like `topic:billing` or `agent:Researcher` work best with `TagFilter`.

## Migration guide

1. **Keep the same session_id** when moving frameworks.
2. Replace framework-specific memory wiring with the corresponding adapter factory:
   - `create_langchain_memory(...)`
   - `create_langgraph_memory(...)`
   - `create_crewai_memory(...)`
   - `create_autogen_memory(...)`
   - `create_llamaindex_memory(...)`
   - `create_pydantic_ai_memory(...)`
   - `create_openai_agents_memory(...)`
   - `create_haystack_memory(...)`
3. Keep tool prompts stable and reuse existing tags/metadata conventions.
4. Validate role mapping and context formatting after migration.
