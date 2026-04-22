"""AutoGen memory adapters backed by Remembr."""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

from adapters.base.error_handling import with_remembr_fallback
from adapters.base.remembr_adapter_base import BaseRemembrAdapter
from adapters.base.utils import parse_role, truncate_to_token_limit

if TYPE_CHECKING:
    from autogen import ConversableAgent, GroupChat

LOGGER = logging.getLogger(__name__)


class RemembrAutoGenMemory(BaseRemembrAdapter):
    """Injects Remembr-backed context into AutoGen ConversableAgent flows."""

    def __init__(
        self,
        client: Any,
        session_id: str | None = None,
        scope_metadata: dict[str, Any] | None = None,
        max_context_tokens: int = 300,
    ) -> None:
        super().__init__(client=client, session_id=session_id, scope_metadata=scope_metadata)
        self.max_context_tokens = max_context_tokens

    def save_context(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        incoming = self._coerce_message_text(inputs.get("message"))
        outgoing = self._coerce_message_text(outputs.get("message"))
        conversation_id = self._conversation_id(inputs, outputs)
        message_index = self._message_index(inputs, outputs)
        if incoming:
            self._safe_store(
                content=incoming,
                role="user",
                metadata={"direction": "incoming", "conversation_id": conversation_id},
                idempotency_key=self._idempotency_key(conversation_id, message_index, incoming),
            )
        if outgoing:
            self._safe_store(
                content=outgoing,
                role="assistant",
                metadata={"direction": "outgoing", "conversation_id": conversation_id},
                idempotency_key=self._idempotency_key(conversation_id, message_index + 1, outgoing),
            )

    def load_context(self, inputs: dict[str, Any]) -> dict[str, Any]:
        message = self._coerce_message_text(inputs.get("message"))
        if not message:
            return {"context": ""}
        return {"context": self.get_relevant_context(message)}

    @with_remembr_fallback()
    def attach_to_agent(self, agent: "ConversableAgent") -> None:
        """Register pre-send and post-receive hooks on an AutoGen agent."""

        def before_send(message: Any, recipient: Any = None, sender: Any = None, **kwargs: Any) -> Any:
            text = self._coerce_message_text(message)
            conversation_id = self._conversation_id(kwargs, message)
            message_index = self._message_index(kwargs, message)
            if text:
                self._safe_store(
                    content=text,
                    role="assistant",
                    metadata={
                        "direction": "outgoing",
                        "sender": getattr(sender, "name", None),
                        "recipient": getattr(recipient, "name", None),
                        "conversation_id": conversation_id,
                    },
                    idempotency_key=self._idempotency_key(conversation_id, message_index, text),
                )
                if isinstance(message, str):
                    return self.inject_context_into_message(message)
                if isinstance(message, dict):
                    updated = dict(message)
                    updated_content = self.inject_context_into_message(self._coerce_message_text(message))
                    if "content" in updated:
                        updated["content"] = updated_content
                    else:
                        updated["message"] = updated_content
                    return updated
            return message

        def after_receive(message: Any, sender: Any = None, recipient: Any = None, **kwargs: Any) -> Any:
            text = self._coerce_message_text(message)
            conversation_id = self._conversation_id(kwargs, message)
            message_index = self._message_index(kwargs, message)
            if text:
                self._safe_store(
                    content=text,
                    role="user",
                    metadata={
                        "direction": "incoming",
                        "sender": getattr(sender, "name", None),
                        "recipient": getattr(recipient, "name", None),
                        "conversation_id": conversation_id,
                    },
                    idempotency_key=self._idempotency_key(conversation_id, message_index, text),
                )
                # Trigger retrieval to warm memory path (best-effort).
                self._safe_get_relevant_context(text)
            return message

        agent.register_hook("process_message_before_send", before_send)
        agent.register_hook("process_message_after_receive", after_receive)

    @with_remembr_fallback(default_value="")
    def get_relevant_context(self, message: str) -> str:
        """Search memory and return a compact context block."""
        if not message.strip():
            return ""

        try:
            result = self._search(query=message, limit=10)
        except Exception as err:  # pragma: no cover - defensive behavior
            LOGGER.warning("Remembr search failed while fetching context: %s", err)
            return ""

        snippets: list[str] = []
        for item in result.results:
            snippets.append(f"- ({parse_role(item.role)}) {item.content}")

        if not snippets:
            return ""

        context = "Relevant memory:\n" + "\n".join(snippets)
        return truncate_to_token_limit(context, self.max_context_tokens)

    @with_remembr_fallback(default_value="")
    def inject_context_into_message(self, message: str) -> str:
        """Prepend retrieved context while respecting configured token budget."""
        context = self._safe_get_relevant_context(message)
        if not context:
            return message
        return f"{context}\n\nCurrent message:\n{message}"

    def _safe_store(
        self,
        *,
        content: str,
        role: str,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        try:
            self._store(
                content=content,
                role=role,
                metadata=metadata or {},
                idempotency_key=idempotency_key,
            )
        except Exception as err:  # pragma: no cover - defensive behavior
            LOGGER.warning("Remembr store failed in AutoGen hook: %s", err)

    def _safe_get_relevant_context(self, message: str) -> str:
        try:
            return self.get_relevant_context(message)
        except Exception as err:  # pragma: no cover - defensive behavior
            LOGGER.warning("Remembr context retrieval failed in AutoGen hook: %s", err)
            return ""

    @staticmethod
    def _coerce_message_text(message: Any) -> str:
        if message is None:
            return ""
        if isinstance(message, str):
            return message
        if isinstance(message, dict):
            value = message.get("content")
            if isinstance(value, str):
                return value
            alt = message.get("message")
            if isinstance(alt, str):
                return alt
        return str(message)

    @staticmethod
    def _truncate_to_token_budget(text: str, max_context_tokens: int) -> str:
        if max_context_tokens <= 0:
            return ""
        tokens = text.split()
        if len(tokens) <= max_context_tokens:
            return text
        return " ".join(tokens[:max_context_tokens])

    @staticmethod
    def _conversation_id(*candidates: Any) -> str:
        for candidate in candidates:
            if isinstance(candidate, dict):
                for key in ("conversation_id", "chat_id", "thread_id"):
                    value = candidate.get(key)
                    if value is not None:
                        return str(value)
            value = getattr(candidate, "conversation_id", None)
            if value is not None:
                return str(value)
        return "default"

    @staticmethod
    def _message_index(*candidates: Any) -> int:
        for candidate in candidates:
            if isinstance(candidate, dict):
                value = candidate.get("message_index")
                if isinstance(value, int):
                    return value
            value = getattr(candidate, "message_index", None)
            if isinstance(value, int):
                return value
        return 0

    @staticmethod
    def _idempotency_key(conversation_id: str, message_index: int, _content: str) -> str:
        return f"autogen-{conversation_id}-{message_index}"


class RemembrAutoGenGroupChatMemory(RemembrAutoGenMemory):
    """GroupChat adapter that stores messages across speakers with agent scoping."""

    @with_remembr_fallback()
    def attach_to_group_chat(self, group_chat: "GroupChat") -> None:
        """Patch group chat append path to persist speaker-tagged messages."""
        original_append = getattr(group_chat, "append", None)
        if not callable(original_append):
            raise AttributeError("group_chat must expose an append(message, speaker) method")

        def wrapped_append(message: Any, speaker: Any = None, *args: Any, **kwargs: Any) -> Any:
            speaker_name = getattr(speaker, "name", None) or "unknown"
            text = self._coerce_message_text(message)
            if text:
                scoped_content = f"[{speaker_name}] {text}"
                self._safe_store(
                    content=scoped_content,
                    role="user",
                    metadata={"speaker": speaker_name, "group_chat": True},
                )
            return original_append(message, speaker, *args, **kwargs)

        group_chat.append = wrapped_append  # type: ignore[method-assign]

    @with_remembr_fallback(default_value="")
    def query_agent_memory(self, agent_name: str, query: str) -> str:
        """Query memories and return only entries attributed to a given agent."""
        try:
            result = self._search(query=query, limit=30)
        except Exception as err:  # pragma: no cover - defensive behavior
            LOGGER.warning("Remembr search failed while querying agent memory: %s", err)
            return ""

        lines: list[str] = []
        marker = f"[{agent_name}]"
        for item in result.results:
            if marker.lower() not in item.content.lower():
                continue
            lines.append(f"- ({agent_name}) {item.content}")

        if not lines:
            return ""
        return truncate_to_token_limit("\n".join(lines), self.max_context_tokens)
