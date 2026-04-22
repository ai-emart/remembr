"""CrewAI memory adapters backed by Remembr."""

from __future__ import annotations

import json
from typing import Any

try:
    from crewai.memory import BaseMemory
except Exception:  # pragma: no cover - crewai may be absent in test environments
    class BaseMemory:  # type: ignore[override]
        """Fallback BaseMemory shim when CrewAI isn't installed."""

        def save(self, value: Any) -> None:  # pragma: no cover - shim
            raise NotImplementedError

        def search(self, query: str) -> list[Any]:  # pragma: no cover - shim
            raise NotImplementedError

        def reset(self) -> None:  # pragma: no cover - shim
            raise NotImplementedError

from adapters.base.error_handling import with_remembr_fallback
from adapters.base.remembr_adapter_base import BaseRemembrAdapter
from adapters.base.utils import parse_role


class RemembrCrewMemory(BaseRemembrAdapter, BaseMemory):
    """Two-layer CrewAI memory: short-term agent scope + long-term team scope."""

    def __init__(
        self,
        client: Any,
        *,
        agent_id: str,
        agent_role: str | None = None,
        team_id: str,
        short_term_session_id: str | None = None,
        long_term_session_id: str | None = None,
        scope_metadata: dict[str, Any] | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.agent_role = agent_role or agent_id
        self.team_id = team_id

        short_scope_metadata = {
            **(scope_metadata or {}),
            "memory_layer": "short_term",
            "agent_id": agent_id,
            "team_id": team_id,
        }
        BaseRemembrAdapter.__init__(
            self,
            client=client,
            session_id=short_term_session_id,
            scope_metadata=short_scope_metadata,
        )
        self.short_term_session_id = self.session_id

        if long_term_session_id:
            self.long_term_session_id = long_term_session_id
        else:
            long_term_session = self._run(
                self.client.create_session(
                    metadata={
                        **(scope_metadata or {}),
                        "memory_layer": "long_term",
                        "team_id": team_id,
                        "agent_id": agent_id,
                    }
                )
            )
            self.long_term_session_id = long_term_session.session_id

    @property
    def short_term(self) -> str:
        return self.short_term_session_id

    @property
    def long_term(self) -> str:
        return self.long_term_session_id

    @staticmethod
    def _stringify(value: Any) -> str:
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, sort_keys=True)
        except TypeError:
            return str(value)

    @with_remembr_fallback()
    def save(self, value: Any) -> None:
        content = self._stringify(value)
        agent_tag = f"agent:{self.agent_role}"
        self._run(
            self.client.store(
                content=content,
                role="user",
                session_id=self.short_term_session_id,
                tags=[agent_tag],
                metadata={"layer": "short_term", "agent_id": self.agent_id, "team_id": self.team_id},
            )
        )
        self._run(
            self.client.store(
                content=content,
                role="user",
                session_id=self.long_term_session_id,
                tags=[agent_tag],
                metadata={"layer": "long_term", "team_id": self.team_id, "agent_id": self.agent_id},
            )
        )

    @with_remembr_fallback(default_value=[])
    def search(self, query: str) -> list[Any]:
        short_results = self._run(self.client.search(query=query, session_id=self.short_term_session_id)).results
        long_results = self._run(self.client.search(query=query, session_id=self.long_term_session_id)).results

        merged: list[Any] = []
        seen: set[str] = set()

        for result in [*short_results, *long_results]:
            key = getattr(result, "episode_id", None) or f"{parse_role(getattr(result, 'role', ''))}:{result.content}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(result)

        return merged

    @with_remembr_fallback()
    def reset(self) -> None:
        self._run(self.client.forget_session(self.short_term_session_id))

    @with_remembr_fallback()
    def save_context(self, inputs: dict[str, Any], outputs: dict[str, Any]) -> None:
        value = {"inputs": inputs, "outputs": outputs}
        self.save(value)

    @with_remembr_fallback(default_value={"results": []})
    def load_context(self, inputs: dict[str, Any]) -> dict[str, Any]:
        query = str(inputs.get("query") or inputs.get("input") or "").strip()
        if not query:
            return {"results": []}
        return {"results": self.search(query)}


class RemembrSharedCrewMemory(RemembrCrewMemory):
    """Shared memory for multi-agent crews using team-scoped long-term memory."""

    def __init__(self, client: Any, *, team_id: str, team_session_id: str | None = None) -> None:
        super().__init__(
            client,
            agent_id="shared",
            agent_role="shared",
            team_id=team_id,
            short_term_session_id=team_session_id,
            long_term_session_id=team_session_id,
            scope_metadata={"shared": True},
        )

    @with_remembr_fallback()
    def save(self, value: Any) -> None:
        content = self._stringify(value)
        self._run(
            self.client.store(
                content=content,
                role="user",
                session_id=self.long_term_session_id,
                tags=[f"agent:{self.agent_role}"],
                metadata={"layer": "shared", "team_id": self.team_id, "agent_id": self.agent_id},
            )
        )

    @with_remembr_fallback(default_value=[])
    def search(self, query: str) -> list[Any]:
        return self._run(self.client.search(query=query, session_id=self.long_term_session_id)).results

    @with_remembr_fallback()
    def reset(self) -> None:
        """Intentionally preserve shared long-term memory for crew continuity."""
        return None

    def inject_into_crew(self, crew: Any) -> None:
        for agent in getattr(crew, "agents", []):
            agent_id = str(getattr(agent, "id", None) or getattr(agent, "role", None) or "agent")
            agent_role = str(getattr(agent, "role", None) or agent_id)
            setattr(
                agent,
                "memory",
                RemembrCrewMemory(
                    self.client,
                    agent_id=agent_id,
                    agent_role=agent_role,
                    team_id=self.team_id,
                    short_term_session_id=self.long_term_session_id,
                    long_term_session_id=self.long_term_session_id,
                    scope_metadata={"shared": True, "agent_id": agent_id},
                ),
            )
