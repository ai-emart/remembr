"""Pydantic AI dependency-injection adapter for Remembr memory."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from remembr import SearchWeights

from adapters.base.error_handling import with_remembr_fallback
from adapters.base.utils import format_messages_for_llm, parse_role

if TYPE_CHECKING:
    from remembr import RemembrClient

try:
    from pydantic_ai import Agent, RunContext
    from pydantic_ai.tools import tool
except Exception:  # pragma: no cover
    class RunContext:  # type: ignore[override]
        def __init__(self, deps: Any):
            self.deps = deps

    def tool(fn):  # type: ignore[misc]
        return fn

    class Agent:  # type: ignore[override]
        def __init__(self, model: Any, system_prompt: Any = None, deps_type: Any = None, tools: list[Any] | None = None, **kwargs: Any):
            self.model = model
            self.system_prompt = system_prompt
            self.deps_type = deps_type
            self.tools = tools or []
            self.kwargs = kwargs


@dataclass
class RemembrMemoryDep:
    client: "RemembrClient"
    session_id: str
    auto_store: bool = True
    max_context_results: int = 5
    search_mode: str = "hybrid"
    weights: SearchWeights | dict[str, float] | None = None


class RemembrMemoryTools:
    """Toolset for explicit agent-side Remembr memory interaction."""

    @staticmethod
    @tool
    @with_remembr_fallback(default_value="")
    def search_memory(ctx: RunContext[RemembrMemoryDep], query: str) -> str:
        if not query.strip():
            return "No query provided."

        result = _run_async(
            ctx.deps.client.search(
                query=query,
                session_id=ctx.deps.session_id,
                limit=ctx.deps.max_context_results,
                search_mode=ctx.deps.search_mode,
                weights=ctx.deps.weights,
            )
        )
        if not result.results:
            return "No relevant memories found."

        lines = ["Relevant memories:"]
        for item in result.results:
            lines.append(f"- ({parse_role(item.role)}) {item.content}")
        return "\n".join(lines)

    @staticmethod
    @tool
    @with_remembr_fallback(default_value="")
    def store_memory(ctx: RunContext[RemembrMemoryDep], content: str, tags: list[str] | None = None) -> str:
        if not content.strip():
            return "Cannot store empty memory."

        episode = _run_async(
            ctx.deps.client.store(
                content=content,
                role="user",
                session_id=ctx.deps.session_id,
                tags=tags or [],
                metadata={"source": "pydantic_ai_tool"},
                idempotency_key=_run_idempotency_key(ctx),
            )
        )
        status = getattr(episode, "embedding_status", None) or "unknown"
        return f"Stored memory {episode.episode_id} (embedding_status={status})."

    @staticmethod
    @tool
    @with_remembr_fallback(default_value="")
    def forget_memory(ctx: RunContext[RemembrMemoryDep], episode_id: str) -> str:
        if not episode_id.strip():
            return "episode_id is required."

        _run_async(ctx.deps.client.forget_episode(episode_id))
        return f"Forgot memory {episode_id}."


@with_remembr_fallback(default_value="Memory lookup unavailable; proceed without prior memory context.")
def remembr_system_prompt(ctx: RunContext[RemembrMemoryDep]) -> str:
    """Dynamic system prompt context with bounded startup latency (<=2s)."""

    def _fetch() -> str:
        result = _run_async(
            ctx.deps.client.search(
                query="recent user preferences and durable facts",
                session_id=ctx.deps.session_id,
                limit=ctx.deps.max_context_results,
                search_mode=ctx.deps.search_mode,
                weights=ctx.deps.weights,
            )
        )
        if not result.results:
            return "No prior memories."

        return format_messages_for_llm(result.results) or "No prior memories."

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_fetch)
        try:
            return future.result(timeout=2.0)
        except FuturesTimeoutError:
            return "Memory lookup timed out; proceed without prior memory context."
        except Exception:
            return "Memory lookup unavailable; proceed without prior memory context."


def create_remembr_agent(
    model: Any,
    system_prompt: str | None,
    api_key: str,
    session_id: str | None = None,
    **agent_kwargs: Any,
) -> Agent:
    from remembr import RemembrClient

    client = RemembrClient(api_key=api_key)
    resolved_session_id = session_id
    if not resolved_session_id:
        created = _run_async(client.create_session(metadata={"source": "pydantic_ai_agent"}))
        resolved_session_id = created.session_id

    deps = RemembrMemoryDep(client=client, session_id=resolved_session_id)

    prompt_components: list[Any] = [remembr_system_prompt]
    if system_prompt:
        prompt_components.insert(0, system_prompt)

    agent = Agent(
        model=model,
        system_prompt=prompt_components,
        deps_type=RemembrMemoryDep,
        tools=[
            RemembrMemoryTools.search_memory,
            RemembrMemoryTools.store_memory,
            RemembrMemoryTools.forget_memory,
        ],
        **agent_kwargs,
    )

    setattr(agent, "remembr_deps", deps)
    return agent


def _run_async(coro: Any) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _run_idempotency_key(ctx: RunContext[RemembrMemoryDep]) -> str | None:
    for source in (ctx, getattr(ctx, "deps", None)):
        if source is None:
            continue
        for attr in ("run_id", "request_id", "conversation_id"):
            value = getattr(source, attr, None)
            if isinstance(value, str) and value.strip():
                return value
    return None
