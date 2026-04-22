"""LangGraph adapters backed by Remembr."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Optional, TYPE_CHECKING

from remembr import SearchWeights

from adapters.base.error_handling import with_remembr_fallback
from adapters.base.remembr_adapter_base import BaseRemembrAdapter
from adapters.base.utils import format_messages_for_llm, parse_role

if TYPE_CHECKING:
    from remembr import RemembrClient

try:
    from langchain_core.runnables import RunnableConfig
except Exception:  # pragma: no cover
    RunnableConfig = dict[str, Any]  # type: ignore[misc,assignment]

try:
    from langgraph.graph import END, START, StateGraph
except Exception:  # pragma: no cover
    START = "__start__"
    END = "__end__"

    class StateGraph:  # type: ignore[override]
        pass

try:
    from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint, CheckpointTuple
except Exception:  # pragma: no cover
    Checkpoint = dict[str, Any]  # type: ignore[misc,assignment]

    @dataclass
    class CheckpointTuple:  # type: ignore[override]
        config: dict[str, Any]
        checkpoint: dict[str, Any]
        metadata: dict[str, Any]

    class BaseCheckpointSaver:  # type: ignore[override]
        pass


def _make_checkpoint_tuple(config: dict[str, Any], checkpoint: dict[str, Any], metadata: dict[str, Any]) -> CheckpointTuple:
    try:
        return CheckpointTuple(config=config, checkpoint=checkpoint, metadata=metadata)
    except TypeError:
        try:
            return CheckpointTuple(config, checkpoint, metadata)
        except TypeError:
            return CheckpointTuple(checkpoint=checkpoint, metadata=metadata)


class RemembrLangGraphMemory(BaseRemembrAdapter):
    """LangGraph node helpers for loading/saving Remembr-backed memory."""

    as_state_key: str = "remembr_context"

    def __init__(
        self,
        client: "RemembrClient",
        session_id: str | None = None,
        scope_metadata: dict[str, Any] | None = None,
        search_mode: str = "hybrid",
        weights: SearchWeights | dict[str, float] | None = None,
    ) -> None:
        super().__init__(client=client, session_id=session_id, scope_metadata=scope_metadata)
        self.search_mode = search_mode
        self.weights = weights

    @with_remembr_fallback(default_value={})
    def load_memories(self, state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        query = self._last_human_message(state)
        context = ""
        if query:
            result = self._search(
                query=query,
                limit=10,
                search_mode=self.search_mode,
                weights=self.weights,
            )
            context = format_messages_for_llm(result.results)

        updated = dict(state)
        updated[self.as_state_key] = context
        return updated

    @with_remembr_fallback(default_value={})
    def save_memories(self, state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
        human_msg, ai_msg = self._latest_exchange(state)
        thread_id = self._thread_id_from_config(config)

        if human_msg:
            self._store(
                content=human_msg,
                role="user",
                metadata={"source": "langgraph", "thread_id": thread_id},
            )
        if ai_msg:
            self._store(
                content=ai_msg,
                role="assistant",
                metadata={"source": "langgraph", "thread_id": thread_id},
            )
        return state

    def save_context(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        self.save_memories({"messages": [inputs, outputs]}, {})

    def load_context(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.load_memories(inputs, {})

    @staticmethod
    def _coerce_message(message: Any) -> tuple[str, str]:
        if isinstance(message, dict):
            return str(message.get("role", "")), str(message.get("content", ""))
        role = getattr(message, "role", "")
        content = getattr(message, "content", "")
        return str(role), str(content)

    def _last_human_message(self, state: dict[str, Any]) -> str:
        messages = state.get("messages") if isinstance(state, dict) else None
        if not isinstance(messages, list):
            return ""
        for msg in reversed(messages):
            role, content = self._coerce_message(msg)
            if parse_role(role) == "user" and content.strip():
                return content
        return ""

    def _latest_exchange(self, state: dict[str, Any]) -> tuple[str, str]:
        messages = state.get("messages") if isinstance(state, dict) else None
        if not isinstance(messages, list):
            return "", ""

        human = ""
        assistant = ""
        for msg in reversed(messages):
            role, content = self._coerce_message(msg)
            normalized = role.lower()
            if not assistant and parse_role(normalized) == "assistant":
                assistant = content
            elif not human and parse_role(normalized) == "user":
                human = content
            if human and assistant:
                break
        return human, assistant

    @staticmethod
    def _thread_id_from_config(config: Any) -> str:
        if isinstance(config, dict):
            configurable = config.get("configurable")
            if isinstance(configurable, dict):
                value = configurable.get("thread_id")
                if value is not None:
                    return str(value)
        return ""


def add_remembr_to_graph(
    graph: StateGraph,
    client: "RemembrClient",
    session_id: str | None = None,
) -> StateGraph:
    """Add Remembr load/save memory nodes around an existing graph."""
    adapter = RemembrLangGraphMemory(client=client, session_id=session_id)

    load_name = "remembr_load_memories"
    save_name = "remembr_save_memories"

    graph.add_node(load_name, adapter.load_memories)
    graph.add_node(save_name, adapter.save_memories)

    existing_nodes = [n for n in list(getattr(graph, "nodes", {}).keys()) if n not in {load_name, save_name}]
    graph.add_edge(START, load_name)

    if existing_nodes:
        first_existing = existing_nodes[0]
        graph.add_edge(load_name, first_existing)

        edge_pairs = list(getattr(graph, "edges", []))
        outgoing = {src for src, _ in edge_pairs if src in existing_nodes}
        terminal_nodes = [n for n in existing_nodes if n not in outgoing]
        for node_name in terminal_nodes or [first_existing]:
            graph.add_edge(node_name, save_name)
    else:
        graph.add_edge(load_name, save_name)

    graph.add_edge(save_name, END)
    return graph


class RemembrLangGraphCheckpointer(BaseCheckpointSaver, BaseRemembrAdapter):
    """LangGraph checkpoint saver backed by Remembr checkpoint APIs."""

    def __init__(
        self,
        client: "RemembrClient",
        session_id: str | None = None,
        scope_metadata: dict[str, Any] | None = None,
    ) -> None:
        BaseRemembrAdapter.__init__(self, client=client, session_id=session_id, scope_metadata=scope_metadata)
        self._checkpoint_index: dict[str, list[dict[str, Any]]] = {}

    def put(self, config: dict[str, Any], checkpoint: Checkpoint, metadata: dict[str, Any]) -> dict[str, Any]:
        thread_id = RemembrLangGraphMemory._thread_id_from_config(config)
        logical_checkpoint_id = str(
            checkpoint.get("id")
            if isinstance(checkpoint, dict) and checkpoint.get("id") is not None
            else metadata.get("checkpoint_id", "checkpoint")
        )
        checkpoint_info = self._run(
            self.client.checkpoint(
                self.session_id,
                idempotency_key=f"lg-{thread_id}-{logical_checkpoint_id}",
            )
        )
        entry = {
            "config": config,
            "checkpoint": dict(checkpoint) if isinstance(checkpoint, dict) else checkpoint,
            "metadata": dict(metadata),
            "remembr_checkpoint_id": checkpoint_info.checkpoint_id,
            "thread_id": thread_id,
        }
        self._checkpoint_index.setdefault(thread_id, []).append(entry)
        return config

    async def aput(self, config: dict[str, Any], checkpoint: Checkpoint, metadata: dict[str, Any]) -> dict[str, Any]:
        return self.put(config, checkpoint, metadata)

    def _checkpoint_entries(self, config: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        thread_id = RemembrLangGraphMemory._thread_id_from_config(config)
        entries = self._checkpoint_index.get(thread_id, [])
        return [
            (
                entry["checkpoint"],
                {
                    **entry["metadata"],
                    "remembr_checkpoint_id": entry["remembr_checkpoint_id"],
                },
            )
            for entry in entries
            if isinstance(entry.get("checkpoint"), dict)
        ]

    def get(self, config: dict[str, Any]) -> Optional[Checkpoint]:
        entries = self._checkpoint_entries(config)
        if not entries:
            return None
        return entries[-1][0]

    async def aget(self, config: dict[str, Any]) -> Optional[Checkpoint]:
        return self.get(config)

    def get_tuple(self, config: dict[str, Any]) -> Optional[CheckpointTuple]:
        entries = self._checkpoint_entries(config)
        if not entries:
            return None
        checkpoint, metadata = entries[-1]
        return CheckpointTuple(config=config, checkpoint=checkpoint, metadata=metadata)

    async def aget_tuple(self, config: dict[str, Any]) -> Optional[CheckpointTuple]:
        return self.get_tuple(config)

    def list(self, config: dict[str, Any]) -> Iterator[CheckpointTuple]:
        entries = self._checkpoint_entries(config)
        for checkpoint, metadata in entries:
            yield _make_checkpoint_tuple(config=config, checkpoint=checkpoint, metadata=metadata)

    async def alist(self, config: dict[str, Any]) -> list[CheckpointTuple]:
        return list(self.list(config))

    def save_context(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        return None

    def load_context(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {}

    def put_writes(self, config: dict[str, Any], writes: Any, task_id: str | None = None) -> None:
        return None

    async def aput_writes(self, config: dict[str, Any], writes: Any, task_id: str | None = None) -> None:
        return None

    def restore_checkpoint(self, config: dict[str, Any], checkpoint_id: str | None = None) -> dict[str, Any]:
        thread_id = RemembrLangGraphMemory._thread_id_from_config(config)
        entries = self._checkpoint_index.get(thread_id, [])
        if not entries:
            raise ValueError("No checkpoints available for this thread")

        target = entries[-1]
        if checkpoint_id is not None:
            for entry in entries:
                if entry["remembr_checkpoint_id"] == checkpoint_id:
                    target = entry
                    break

        return self._run(self.client.restore(self.session_id, target["remembr_checkpoint_id"]))
