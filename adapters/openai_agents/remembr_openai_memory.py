"""OpenAI Agents SDK adapter for Remembr memory tools and hooks."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, TYPE_CHECKING

from adapters.base.error_handling import with_remembr_fallback
from adapters.base.utils import format_messages_for_llm

if TYPE_CHECKING:
    from remembr import RemembrClient

try:
    from openai_agents import Agent, AgentHooks, Handoff, function_tool
except Exception:  # pragma: no cover
    def function_tool(fn):  # type: ignore[misc]
        fn.is_function_tool = True
        return fn

    class AgentHooks:  # type: ignore[override]
        pass

    class Agent:  # type: ignore[override]
        def __init__(self, name: str, instructions: str, model: str, tools: list[Any] | None = None, hooks: Any = None, **kwargs: Any):
            self.name = name
            self.instructions = instructions
            self.model = model
            self.tools = tools or []
            self.hooks = hooks
            self.kwargs = kwargs

    class Handoff:  # type: ignore[override]
        def __init__(self):
            self.on_handoff = None


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


def _schedule(coro: Any) -> None:
    try:
        asyncio.create_task(coro)
    except RuntimeError:
        def _runner() -> None:
            asyncio.run(coro)

        threading.Thread(target=_runner, daemon=True).start()


class RemembrMemoryTools:
    """Function tools that expose Remembr memory operations to agents."""

    client: "RemembrClient | None" = None

    @classmethod
    def configure(cls, client: "RemembrClient") -> None:
        cls.client = client

    @staticmethod
    @function_tool
    @with_remembr_fallback(default_value="")
    def search_memory(query: str, session_id: str) -> str:
        """Return a plain-text summary of matching memories for a session."""
        client = RemembrMemoryTools.client
        if client is None:
            return "Remembr client is not configured."
        if not query.strip() or not session_id.strip():
            return "query and session_id are required."

        result = _run_async(
            client.search(query=query, session_id=session_id, limit=8, search_mode="hybrid")
        )
        if not result.results:
            return "No relevant memories found."
        lines = ["Relevant memories:"]
        for item in result.results:
            lines.append(f"- ({item.role}) {item.content}")
        return "\n".join(lines)

    @staticmethod
    @function_tool
    @with_remembr_fallback(default_value="")
    def store_memory(content: str, session_id: str, tags: str = "") -> str:
        """Store a memory and return the episode ID plus embedding_status from the SDK response."""
        client = RemembrMemoryTools.client
        if client is None:
            return "Remembr client is not configured."
        if not content.strip() or not session_id.strip():
            return "content and session_id are required."

        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        episode = _run_async(
            client.store(
                content=content,
                role="user",
                session_id=session_id,
                tags=tag_list,
                metadata={"source": "openai_agents_tool"},
            )
        )
        status = getattr(episode, "embedding_status", None) or "unknown"
        return f"Stored memory {episode.episode_id} (embedding_status={status})."

    @staticmethod
    @function_tool
    @with_remembr_fallback(default_value="")
    def get_session_summary(session_id: str) -> str:
        client = RemembrMemoryTools.client
        if client is None:
            return "Remembr client is not configured."
        if not session_id.strip():
            return "session_id is required."

        history = _run_async(client.get_session_history(session_id=session_id, limit=30))
        if not history:
            return "No messages in session history yet."

        formatted = format_messages_for_llm(history[-10:])
        return f"Session {session_id} summary (latest {len(history)} entries):\n{formatted}"


class RemembrAgentHooks(AgentHooks):
    """OpenAI Agents lifecycle hooks that auto-log to Remembr."""

    def __init__(self, client: "RemembrClient", session_id: str) -> None:
        self.client = client
        self.session_id = session_id

    async def _store_async(self, content: str, role: str, metadata: dict[str, Any] | None = None) -> None:
        await self.client.store(
            content=content,
            role=role,
            session_id=self.session_id,
            metadata=metadata or {},
        )

    @with_remembr_fallback()
    def on_tool_end(self, context: Any, agent: Any, tool: Any, result: Any) -> None:
        tool_name = getattr(tool, "name", str(tool))
        content = f"Tool completed: {tool_name}; result={result}"
        _schedule(self._store_async(content, role="tool", metadata={"event": "on_tool_end", "agent": getattr(agent, "name", "")}))

    @with_remembr_fallback()
    def on_handoff(self, context: Any, agent: Any, source: Any) -> None:
        source_name = getattr(source, "name", str(source))
        content = f"Handoff received from {source_name}."
        _schedule(self._store_async(content, role="handoff", metadata={"event": "on_handoff", "agent": getattr(agent, "name", "")}))

    @with_remembr_fallback()
    def on_agent_end(self, context: Any, agent: Any, output: Any) -> None:
        content = f"Agent output: {output}"
        _schedule(self._store_async(content, role="assistant", metadata={"event": "on_agent_end", "agent": getattr(agent, "name", "")}))


class RemembrHandoffMemory:
    """Thread-safe handoff memory helper for multi-agent workflows."""

    def __init__(self, client: "RemembrClient", session_id: str) -> None:
        self.client = client
        self.session_id = session_id
        self._lock = threading.Lock()

    async def _store_handoff(self, source_agent: str, payload: str) -> None:
        await self.client.store(
            content=f"Handoff context from {source_agent}: {payload}",
            role="handoff",
            session_id=self.session_id,
            metadata={"source_agent": source_agent, "kind": "handoff"},
        )

    async def _search_handoff(self, receiver_agent: str) -> str:
        result = await self.client.search(
            query=f"handoff context for {receiver_agent}",
            session_id=self.session_id,
            limit=5,
            search_mode="hybrid",
        )
        return "\n".join([f"- {x.content}" for x in result.results])

    def store_before_handoff(self, source_agent: str, payload: str) -> None:
        with self._lock:
            _schedule(self._store_handoff(source_agent, payload))

    @with_remembr_fallback(default_value="")
    def inject_after_handoff(self, receiver_agent: str) -> str:
        with self._lock:
            return _run_async(self._search_handoff(receiver_agent))

    def attach_to_handoff(self, handoff: Handoff) -> Handoff:
        original = getattr(handoff, "on_handoff", None)

        def wrapped(context: Any, agent: Any, source: Any) -> Any:
            source_name = getattr(source, "name", str(source))
            self.store_before_handoff(source_name, f"handoff to {getattr(agent, 'name', 'unknown')}")
            if callable(original):
                return original(context, agent, source)
            return None

        handoff.on_handoff = wrapped
        return handoff


def create_remembr_agent(
    name: str,
    instructions: str,
    model: str,
    api_key: str,
    session_id: str | None = None,
    extra_tools: list[Any] | None = None,
    **kwargs: Any,
) -> Agent:
    from remembr import RemembrClient

    client = RemembrClient(api_key=api_key)
    resolved_session_id = session_id
    if not resolved_session_id:
        created = _run_async(client.create_session(metadata={"source": "openai_agents"}))
        resolved_session_id = created.session_id

    RemembrMemoryTools.configure(client)

    memory_context = RemembrMemoryTools.get_session_summary(resolved_session_id)
    full_instructions = f"{instructions}\n\n[Memory Context]\n{memory_context}\nSession ID: {resolved_session_id}"

    tools = [
        RemembrMemoryTools.search_memory,
        RemembrMemoryTools.store_memory,
        RemembrMemoryTools.get_session_summary,
    ] + (extra_tools or [])

    hooks = RemembrAgentHooks(client=client, session_id=resolved_session_id)
    agent = Agent(
        name=name,
        instructions=full_instructions,
        model=model,
        tools=tools,
        hooks=hooks,
        **kwargs,
    )
    setattr(agent, "remembr_session_id", resolved_session_id)
    setattr(agent, "remembr_client", client)
    return agent
