"""Shared memory wrapper for the LangGraph example."""
# ruff: noqa: E402

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from remembr import RemembrClient, TagFilter

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from adapters.langgraph.remembr_langgraph_memory import RemembrLangGraphMemory
from src.topics import topic_slug


def _normalize_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    content = getattr(value, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif hasattr(item, "get") and isinstance(item.get("text"), str):  # pragma: no cover
                parts.append(item.get("text"))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(value)


def invoke_text(llm: Any, prompt: str) -> str:
    response = llm.invoke(prompt)
    return _normalize_text(response)


def parse_json_block(text: str, fallback: dict[str, Any]) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if "\n" in cleaned:
            cleaned = cleaned.split("\n", 1)[1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return fallback
    return parsed if isinstance(parsed, dict) else fallback


@dataclass
class SessionRegistry:
    path: Path

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def get(self, topic: str) -> str | None:
        return self.load().get(topic_slug(topic))

    def set(self, topic: str, session_id: str) -> None:
        data = self.load()
        data[topic_slug(topic)] = session_id
        self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


class SharedLangGraphMemory:
    """Thin wrapper around the SDK and LangGraph adapter for shared topic sessions."""

    def __init__(self, client: RemembrClient, session_id: str) -> None:
        self.client = client
        self.session_id = session_id
        self.adapter = RemembrLangGraphMemory(client=client, session_id=session_id)

    @classmethod
    def from_client(cls, client: RemembrClient, topic: str, registry: SessionRegistry) -> "SharedLangGraphMemory":
        existing = registry.get(topic)
        if existing:
            return cls(client=client, session_id=existing)

        session = cls._run(
            client.create_session(
                metadata={
                    "example": "langgraph-multi-agent",
                    "topic": topic,
                    "topic_slug": topic_slug(topic),
                }
            )
        )
        registry.set(topic, session.session_id)
        return cls(client=client, session_id=session.session_id)

    @classmethod
    def from_env(cls, topic: str, registry_path: Path | None = None) -> "SharedLangGraphMemory":
        import os

        registry = SessionRegistry(
            registry_path
            or Path(os.getenv("REMEMBR_TOPIC_REGISTRY", ".remembr-topic-sessions.json"))
        )
        client = RemembrClient(
            api_key=os.environ["REMEMBR_API_KEY"],
            base_url=os.getenv("REMEMBR_BASE_URL", "http://localhost:8000/api/v1"),
        )
        return cls.from_client(client=client, topic=topic, registry=registry)

    @staticmethod
    def _run(coro: Any) -> Any:
        return RemembrLangGraphMemory._run(coro)

    def write_memory(
        self,
        *,
        agent: str,
        topic: str,
        kind: str,
        content: str,
        extra_tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        tags = [
            f"agent:{agent}",
            f"topic:{topic_slug(topic)}",
            f"kind:{kind}",
            *(extra_tags or []),
        ]
        return self.adapter._store(
            content=content,
            role="assistant",
            tags=tags,
            metadata={"agent": agent, "kind": kind, **(metadata or {})},
        )

    def read_memories(
        self,
        *,
        topic: str,
        kind: str | None = None,
        agent: str | None = None,
        query: str | None = None,
        limit: int = 10,
        search_mode: str = "keyword",
    ) -> list[str]:
        filters = [TagFilter(key="topic", value=topic_slug(topic))]
        if kind is not None:
            filters.append(TagFilter(key="kind", value=kind))
        if agent is not None:
            filters.append(TagFilter(key="agent", value=agent))

        result = self.adapter._search(
            query=query or topic,
            limit=limit,
            search_mode=search_mode,
            tag_filters=filters,
        )
        return [item.content for item in result.results]

    def previous_feedback(self, topic: str, limit: int = 5) -> list[str]:
        return self.read_memories(
            topic=topic,
            kind="feedback",
            query=topic,
            limit=limit,
            search_mode="keyword",
        )

    def research_findings(self, topic: str, limit: int = 8) -> list[str]:
        return self.read_memories(
            topic=topic,
            kind="finding",
            query=topic,
            limit=limit,
            search_mode="keyword",
        )

    def latest_draft(self, topic: str) -> str:
        drafts = self.read_memories(
            topic=topic,
            kind="draft",
            agent="writing",
            query=topic,
            limit=1,
            search_mode="keyword",
        )
        return drafts[0] if drafts else ""
