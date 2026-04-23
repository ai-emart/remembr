"""LlamaIndex adapters backed by Remembr."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from remembr import SearchWeights, TagFilter
from pydantic import Field

from adapters.base.error_handling import with_remembr_fallback
from adapters.base.remembr_adapter_base import BaseRemembrAdapter
from adapters.base.utils import parse_role

if TYPE_CHECKING:
    from remembr import RemembrClient

try:
    from llama_index.core.base.llms.types import ChatMessage, MessageRole
    from llama_index.core.memory import ChatMemoryBuffer
    from llama_index.core.storage.chat_store import BaseChatStore
except Exception:  # pragma: no cover
    class MessageRole:
        USER = "user"
        ASSISTANT = "assistant"
        SYSTEM = "system"

    @dataclass
    class ChatMessage:
        role: Any
        content: str

    class BaseChatStore:
        def get_messages(self, key: str) -> list[ChatMessage]:
            raise NotImplementedError

        def add_message(self, key: str, message: ChatMessage) -> None:
            raise NotImplementedError

        def delete_messages(self, key: str) -> None:
            raise NotImplementedError

        def delete_last_message(self, key: str) -> None:
            raise NotImplementedError

        def delete_message(self, key: str, idx: int) -> None:
            raise NotImplementedError

        def get_keys(self) -> list[str]:
            raise NotImplementedError

        def set_messages(self, key: str, messages: list[ChatMessage]) -> None:
            raise NotImplementedError

    class ChatMemoryBuffer:
        def __init__(self, chat_store: BaseChatStore | None = None, chat_store_key: str | None = None, token_limit: int = 2048, **kwargs: Any) -> None:
            self.chat_store = chat_store
            self.chat_store_key = chat_store_key
            self.token_limit = token_limit


class RemembrChatStore(BaseChatStore):
    """Drop-in chat store where keys map directly to Remembr session IDs."""

    client: Any = Field(default=None, exclude=True)

    def __init__(self, client: "RemembrClient", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        object.__setattr__(self, "client", client)

    @staticmethod
    def _run(coro: Any) -> Any:
        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    @with_remembr_fallback(default_value=[])
    def get_messages(self, key: str) -> list[ChatMessage]:
        episodes = self._run(self.client.get_session_history(session_id=key, limit=200))
        messages: list[ChatMessage] = []
        for ep in episodes:
            role = MessageRole.ASSISTANT if parse_role(ep.role) == "assistant" else MessageRole.USER
            messages.append(ChatMessage(role=role, content=ep.content))
        return messages

    @with_remembr_fallback()
    def add_message(self, key: str, message: ChatMessage) -> None:
        role_value = getattr(message, "role", MessageRole.USER)
        role = str(role_value).lower()
        if "assistant" in role:
            mapped_role = "assistant"
        elif "system" in role:
            mapped_role = "system"
        else:
            mapped_role = "user"

        self._run(
            self.client.store(
                session_id=key,
                content=getattr(message, "content", ""),
                role=mapped_role,
            )
        )

    def delete_messages(self, key: str) -> None:
        self._run(self.client.forget_session(key))

    def delete_last_message(self, key: str) -> None:
        raise NotImplementedError(
            "RemembrChatStore.delete_last_message is not implemented yet."
        )

    def delete_message(self, key: str, idx: int) -> None:
        raise NotImplementedError("RemembrChatStore.delete_message is not implemented yet.")

    def get_keys(self) -> list[str]:
        raise NotImplementedError("RemembrChatStore.get_keys is not implemented yet.")

    def set_messages(self, key: str, messages: list[ChatMessage]) -> None:
        raise NotImplementedError("RemembrChatStore.set_messages is not implemented yet.")


class RemembrMemoryBuffer(ChatMemoryBuffer):
    """Memory buffer that retrieves relevant context from Remembr.

    Notes:
        Newly stored messages may have ``embedding_status="pending"``. Immediate retrieval after
        ``add_message`` may not surface them until embedding generation completes.
    """

    client: Any = Field(default=None, exclude=True)
    session_id: str = Field(default="")
    search_limit: int = Field(default=20)
    search_mode: str = Field(default="hybrid")
    tag_filters: list[TagFilter] | None = Field(default=None)
    weights: SearchWeights | dict[str, float] | None = Field(default=None, exclude=True)
    chat_store: Any = Field(default=None, exclude=True)

    def __init__(
        self,
        client: "RemembrClient",
        session_id: str,
        token_limit: int = 2048,
        search_limit: int = 20,
        search_mode: str = "hybrid",
        tag_filters: list[TagFilter] | None = None,
        weights: SearchWeights | dict[str, float] | None = None,
        **kwargs: Any,
    ) -> None:
        object.__setattr__(self, "client", client)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "search_limit", search_limit)
        object.__setattr__(self, "search_mode", search_mode)
        object.__setattr__(self, "tag_filters", tag_filters)
        object.__setattr__(self, "weights", weights)
        object.__setattr__(self, "chat_store", RemembrChatStore(client))
        super().__init__(
            chat_store=self.chat_store,
            chat_store_key=session_id,
            token_limit=token_limit,
            **kwargs,
        )

    @with_remembr_fallback(default_value=[])
    def get(self, input: str | None = None, **kwargs: Any) -> list[ChatMessage]:
        query = (input or kwargs.get("query") or "").strip()
        if not query:
            messages = self.chat_store.get_messages(self.session_id)
            return self._clip_to_token_limit(messages)

        result = self.chat_store._run(
            self.client.search(
                query=query,
                session_id=self.session_id,
                limit=self.search_limit,
                search_mode=self.search_mode,
                tag_filters=self.tag_filters,
                weights=self.weights,
            )
        )
        messages: list[ChatMessage] = []
        for item in result.results:
            role = MessageRole.ASSISTANT if parse_role(item.role) == "assistant" else MessageRole.USER
            messages.append(ChatMessage(role=role, content=item.content))
        return self._clip_to_token_limit(messages)

    def _clip_to_token_limit(self, messages: list[ChatMessage]) -> list[ChatMessage]:
        total_tokens = 0
        clipped: list[ChatMessage] = []
        for msg in messages:
            est = max(1, len((msg.content or "").split()))
            if total_tokens + est > self.token_limit:
                break
            clipped.append(msg)
            total_tokens += est
        return clipped


class _RemembrRetriever:
    def __init__(self, client: "RemembrClient", session_id: str | None = None, search_kwargs: dict[str, Any] | None = None) -> None:
        self.client = client
        self.session_id = session_id
        self.search_kwargs = search_kwargs or {}

    def retrieve(self, query: str) -> list[dict[str, Any]]:
        import asyncio

        async def _do() -> Any:
            return await self.client.search(query=query, session_id=self.session_id, **self.search_kwargs)

        try:
            result = asyncio.run(_do())
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                result = loop.run_until_complete(_do())
            finally:
                loop.close()

        return [
            {
                "id": item.episode_id,
                "text": item.content,
                "score": item.score,
                "metadata": {"role": item.role, "created_at": str(item.created_at)},
            }
            for item in result.results
        ]


class RemembrSemanticMemory(BaseRemembrAdapter):
    """RAG-style retriever wrapper aligned with LlamaIndex retriever patterns."""

    def __init__(
        self,
        client: "RemembrClient",
        session_id: str | None = None,
        scope_metadata: dict[str, Any] | None = None,
        search_kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(client=client, session_id=session_id, scope_metadata=scope_metadata)
        self.search_kwargs = search_kwargs or {"limit": 10, "search_mode": "hybrid"}

    @classmethod
    def from_client(
        cls,
        client: "RemembrClient",
        session_id: str | None = None,
        scope_metadata: dict[str, Any] | None = None,
        search_kwargs: dict[str, Any] | None = None,
    ) -> "RemembrSemanticMemory":
        return cls(
            client=client,
            session_id=session_id,
            scope_metadata=scope_metadata,
            search_kwargs=search_kwargs,
        )

    def as_retriever(
        self,
        *,
        search_mode: str | None = None,
        tag_filters: list[TagFilter] | None = None,
    ) -> _RemembrRetriever:
        search_kwargs = dict(self.search_kwargs)
        if search_mode is not None:
            search_kwargs["search_mode"] = search_mode
        if tag_filters is not None:
            search_kwargs["tag_filters"] = tag_filters
        return _RemembrRetriever(
            client=self.client,
            session_id=self.session_id,
            search_kwargs=search_kwargs,
        )

    def save_context(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        if inputs.get("input"):
            self._store(content=str(inputs["input"]), role="user")
        if outputs.get("output"):
            self._store(content=str(outputs["output"]), role="assistant")

    def load_context(self, inputs: dict[str, Any]) -> dict[str, Any]:
        query = str(inputs.get("input") or "").strip()
        if not query:
            return {"results": []}
        result = self._search(query=query, **self.search_kwargs)
        return {"results": result.results}
