"""Haystack memory components backed by Remembr."""

from __future__ import annotations

import asyncio
from typing import Any, TYPE_CHECKING

from remembr import TagFilter

if TYPE_CHECKING:
    from remembr import RemembrClient

try:
    from haystack import Pipeline, component
    from haystack.components.builders import PromptBuilder
except Exception:  # pragma: no cover
    class _ComponentDecorator:
        def __call__(self, cls):
            cls.__haystack_component__ = True
            return cls

        def output_types(self, **kwargs):
            def deco(fn):
                fn.__haystack_output_types__ = kwargs
                return fn

            return deco

    component = _ComponentDecorator()

    class Pipeline:  # type: ignore[override]
        def __init__(self):
            self.components: dict[str, Any] = {}
            self.connections: list[tuple[str, str]] = []

        def add_component(self, name: str, instance: Any) -> None:
            self.components[name] = instance

        def connect(self, source: str, target: str) -> None:
            self.connections.append((source, target))

        def run(self, data: dict[str, Any]):
            return {"data": data}

    class PromptBuilder:  # type: ignore[override]
        def __init__(self, template: str):
            self.template = template


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


@component
class RemembrMemoryRetriever:
    """Haystack component for Remembr retrieval.

    Notes:
        If this retriever runs in the same pipeline invocation as a store step, newly written
        memories may still be pending embedding and may not be returned immediately.
    """

    def __init__(self, client: "RemembrClient", default_session_id: str | None = None):
        self.client = client
        self.default_session_id = default_session_id

    @component.output_types(memories=list[str], episode_ids=list[str])
    def run(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 5,
        search_mode: str = "hybrid",
        tag_filters: list[TagFilter] | None = None,
    ) -> dict[str, Any]:
        sid = session_id or self.default_session_id
        if not query.strip() or not sid:
            return {"memories": [], "episode_ids": []}

        result = _run_async(
            self.client.search(
                query=query,
                session_id=sid,
                limit=limit,
                search_mode=search_mode,
                tag_filters=tag_filters,
            )
        )
        memories = [f"({item.role}) {item.content}" for item in result.results]
        episode_ids = [item.episode_id for item in result.results]
        return {"memories": memories, "episode_ids": episode_ids}


@component
class RemembrMemoryWriter:
    """Haystack component for storing episodic memory entries in Remembr."""

    def __init__(self, client: "RemembrClient", default_session_id: str | None = None):
        self.client = client
        self.default_session_id = default_session_id

    @component.output_types(episode_id=str, stored=bool)
    def run(
        self,
        content: str,
        role: str = "user",
        session_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        sid = session_id or self.default_session_id
        if not content.strip() or not sid:
            return {"episode_id": "", "stored": False}

        episode = _run_async(
            self.client.store(
                content=content,
                role=role,
                session_id=sid,
                tags=list(tags or []),
                metadata={"source": "haystack_memory_writer"},
            )
        )
        return {"episode_id": episode.episode_id, "stored": True}


class RemembrConversationMemory:
    """ChatMessageStore-compatible memory layer backed by Remembr."""

    def __init__(
        self,
        client: "RemembrClient",
        session_id: str,
        retrieval_query: str = "recent conversation context",
        search_mode: str = "hybrid",
        tag_filters: list[TagFilter] | None = None,
    ):
        self.client = client
        self.session_id = session_id
        self.retrieval_query = retrieval_query
        self.search_mode = search_mode
        self.tag_filters = tag_filters

    @staticmethod
    def _msg_role(message: Any) -> str:
        role = getattr(message, "role", "user")
        return str(role).lower() if role is not None else "user"

    @staticmethod
    def _msg_text(message: Any) -> str:
        text = getattr(message, "text", None)
        if isinstance(text, str):
            return text
        content = getattr(message, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(message, dict):
            if isinstance(message.get("text"), str):
                return message["text"]
            if isinstance(message.get("content"), str):
                return message["content"]
        return str(message)

    def write_messages(self, messages: list[Any]) -> None:
        for msg in messages:
            _run_async(
                self.client.store(
                    content=self._msg_text(msg),
                    role=self._msg_role(msg),
                    session_id=self.session_id,
                    metadata={"source": "haystack_chat_store"},
                )
            )

    def retrieve(self, limit: int) -> list[Any]:
        results = _run_async(
            self.client.search(
                query=self.retrieval_query,
                session_id=self.session_id,
                limit=limit,
                search_mode=self.search_mode,
                tag_filters=self.tag_filters,
            )
        ).results

        try:
            from haystack.dataclasses import ChatMessage

            return [ChatMessage.from_user(x.content) if x.role != "assistant" else ChatMessage.from_assistant(x.content) for x in results]
        except Exception:  # pragma: no cover
            return [{"role": x.role, "content": x.content, "id": x.episode_id} for x in results]

    def delete_messages(self, ids: list[str]) -> None:
        for eid in ids:
            if eid.strip():
                _run_async(self.client.forget_episode(eid))


def build_remembr_rag_pipeline(
    client: "RemembrClient",
    llm_component: Any,
    session_id: str | None = None,
) -> Pipeline:
    """Build a connected Haystack RAG-style pipeline with Remembr memory components."""
    resolved_session = session_id
    if not resolved_session:
        created = _run_async(client.create_session(metadata={"source": "haystack_rag_pipeline"}))
        resolved_session = created.session_id

    retriever = RemembrMemoryRetriever(client=client, default_session_id=resolved_session)
    prompt_builder = PromptBuilder(
        template=(
            "Use these memories if relevant:\n"
            "{% for memory in memories %}- {{ memory }}\n{% endfor %}\n"
            "Question: {{query}}"
        )
    )
    writer = RemembrMemoryWriter(client=client, default_session_id=resolved_session)

    pipeline = Pipeline()
    pipeline.add_component("memory_retriever", retriever)
    pipeline.add_component("prompt_builder", prompt_builder)
    pipeline.add_component("llm", llm_component)
    pipeline.add_component("memory_writer", writer)

    pipeline.connect("memory_retriever.memories", "prompt_builder.memories")
    pipeline.connect("prompt_builder", "llm")
    pipeline.connect("llm.replies", "memory_writer.content")
    return pipeline
