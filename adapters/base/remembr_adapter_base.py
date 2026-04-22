"""Shared base abstractions for Remembr framework adapters."""

from __future__ import annotations

import abc
import asyncio
from collections.abc import Coroutine
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from remembr import RemembrClient


class BaseRemembrAdapter(abc.ABC):
    """Base class that centralizes common Remembr adapter behavior."""

    def __init__(
        self,
        client: "RemembrClient",
        session_id: str | None = None,
        scope_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.scope_metadata = dict(scope_metadata or {})

        if session_id:
            self.session_id = session_id
        else:
            session = self._run(self.client.create_session(metadata=self.scope_metadata))
            self.session_id = session.session_id

    @staticmethod
    def _run(coro: Coroutine[Any, Any, Any]) -> Any:
        """Run an async SDK call from sync adapter surfaces."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def _store(
        self,
        content: str,
        role: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        return self._run(
            self.client.store(
                content=content,
                role=role,
                session_id=session_id or self.session_id,
                tags=tags or [],
                metadata=metadata or {},
                idempotency_key=idempotency_key,
            )
        )

    def _search(self, query: str, **kwargs: Any) -> Any:
        return self._run(self.client.search(query=query, session_id=self.session_id, **kwargs))

    def _checkpoint(self) -> Any:
        return self._run(self.client.checkpoint(self.session_id))

    @abc.abstractmethod
    def save_context(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        """Persist interaction context in Remembr."""

    @abc.abstractmethod
    def load_context(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Load relevant context from Remembr."""
