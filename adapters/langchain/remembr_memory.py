"""LangChain memory adapter backed by Remembr."""

from __future__ import annotations

import hashlib
from typing import Any

from langchain_core.memory import BaseMemory
from langchain_core.messages import AIMessage, HumanMessage
from remembr import SearchWeights, TagFilter

from adapters.base.error_handling import with_remembr_fallback
from adapters.base.remembr_adapter_base import BaseRemembrAdapter
from adapters.base.utils import parse_role


class RemembrMemory(BaseMemory, BaseRemembrAdapter):
    """Drop-in memory class compatible with LangChain 1.x memory APIs.

    Notes:
        Writes return the SDK store response, which may report ``embedding_status="pending"``.
        Searches performed immediately after a write may not include the just-stored memory until
        embedding generation completes.
    """

    memory_key: str = "history"
    return_messages: bool = True

    def __init__(
        self,
        client: Any,
        session_id: str | None = None,
        scope_metadata: dict[str, Any] | None = None,
        return_messages: bool = True,
        search_mode: str = "hybrid",
        weights: SearchWeights | dict[str, float] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        BaseRemembrAdapter.__init__(
            self,
            client=client,
            session_id=session_id,
            scope_metadata=scope_metadata,
        )
        self.return_messages = return_messages
        self.search_mode = search_mode
        self.weights = weights

    @property
    def memory_variables(self) -> list[str]:
        """Return list of memory variable keys."""
        return [self.memory_key]

    @with_remembr_fallback()
    def save_context(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        """Save context from this conversation turn to Remembr.
        
        Args:
            inputs: Dictionary containing user input (typically with 'input' key)
            outputs: Dictionary containing AI output (typically with 'output' key)
        """
        user_input = str(inputs.get("input", "")).strip()
        ai_output = str(outputs.get("output", "")).strip()

        if user_input:
            self._store_message(user_input, role="user")
        if ai_output:
            self._store_message(ai_output, role="assistant")

    @with_remembr_fallback()
    def add_messages(self, messages: list[Any]) -> None:
        for message in messages:
            role = parse_role(getattr(message, "type", "") or getattr(message, "role", "user"))
            content = str(getattr(message, "content", "")).strip()
            if content:
                self._store_message(content, role=role)

    @with_remembr_fallback(default_value=[])
    def get_messages(
        self,
        query: str | None = None,
        *,
        limit: int = 20,
        tag_filters: list[TagFilter] | None = None,
        search_mode: str | None = None,
        weights: SearchWeights | dict[str, float] | None = None,
    ) -> list[Any]:
        if query and query.strip():
            result = self._search(
                query=query.strip(),
                limit=limit,
                tag_filters=tag_filters,
                search_mode=search_mode or self.search_mode,
                weights=weights or self.weights,
            )
            items = result.results
        else:
            items = self._run(self.client.get_session_history(self.session_id, limit=limit))

        messages: list[Any] = []
        for item in items:
            if parse_role(item.role) == "assistant":
                messages.append(AIMessage(content=item.content))
            else:
                messages.append(HumanMessage(content=item.content))
        return messages

    @with_remembr_fallback(default_value={"history": []})
    def load_memory_variables(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Load memory variables from Remembr based on the current input.
        
        Args:
            inputs: Dictionary containing the current input (typically with 'input' key)
            
        Returns:
            Dictionary with memory_key mapped to conversation history
        """
        query = str(inputs.get("input", "")).strip()
        if not query:
            return {self.memory_key: []}

        if self.return_messages:
            return {
                self.memory_key: self.get_messages(query=query, limit=10),
            }

        results = self._search(
            query=query,
            limit=10,
            search_mode=self.search_mode,
            weights=self.weights,
        )
        context_lines = []
        for item in results.results:
            role = "AI" if parse_role(item.role) == "assistant" else "Human"
            context_lines.append(f"{role}: {item.content}")
        return {self.memory_key: "\n".join(context_lines)}

    @with_remembr_fallback()
    def clear(self) -> None:
        """Clear all memories for this session from Remembr."""
        self._run(self.client.forget_session(self.session_id))

    def load_context(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.load_memory_variables(inputs)

    def _store_message(self, content: str, *, role: str) -> None:
        digest = hashlib.sha256(f"{role}:{content}".encode("utf-8")).hexdigest()[:16]
        self._store(
            content,
            role=role,
            idempotency_key=f"langchain-{self.session_id}-{digest}",
        )
