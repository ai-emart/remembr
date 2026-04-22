"""Memory scoping system for org → team → user → agent hierarchy."""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import and_, false, or_
from sqlalchemy.sql import ColumnElement

from app.middleware.context import RequestContext
from app.models.memory_fact import MemoryFact

ScopeLevel = Literal["org", "team", "user", "agent"]


@dataclass(frozen=True)
class MemoryScope:
    """Scope envelope used for read/write memory access control."""

    org_id: str
    team_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    level: ScopeLevel = "org"

    def __post_init__(self) -> None:
        if self.level == "team" and not self.team_id:
            raise ValueError("team_id required for team-level scope")
        if self.level == "user" and not self.user_id:
            raise ValueError("user_id required for user-level scope")
        if self.level == "agent" and not self.agent_id:
            raise ValueError("agent_id required for agent-level scope")
        if self.agent_id and not self.user_id:
            raise ValueError("user_id required when agent_id is set")


class ScopeResolver:
    """Resolver for deterministic read/write scope evaluation."""

    @staticmethod
    def _id(value: object | None) -> str | None:
        return str(value) if value is not None else None

    @classmethod
    def from_request_context(cls, ctx: RequestContext) -> MemoryScope:
        """Build the most-specific scope available in request context."""
        if ctx.agent_id:
            level: ScopeLevel = "agent"
        elif ctx.user_id:
            level = "user"
        else:
            level = "org"

        return MemoryScope(
            org_id=str(ctx.org_id),
            user_id=cls._id(ctx.user_id),
            agent_id=cls._id(ctx.agent_id),
            level=level,
        )

    @staticmethod
    def resolve_readable_scopes(scope: MemoryScope) -> list[MemoryScope]:
        """Resolve readable scopes according to inheritance rules."""
        if scope.level == "org":
            return [MemoryScope(org_id=scope.org_id, level="org")]

        if scope.level == "team":
            return [
                MemoryScope(org_id=scope.org_id, team_id=scope.team_id, level="team"),
                MemoryScope(org_id=scope.org_id, level="org"),
            ]

        if scope.level == "user":
            scopes = [MemoryScope(org_id=scope.org_id, user_id=scope.user_id, level="user")]
            if scope.team_id:
                scopes.append(MemoryScope(org_id=scope.org_id, team_id=scope.team_id, level="team"))
            scopes.append(MemoryScope(org_id=scope.org_id, level="org"))
            return scopes

        # agent
        scopes = [
            MemoryScope(
                org_id=scope.org_id,
                team_id=scope.team_id,
                user_id=scope.user_id,
                agent_id=scope.agent_id,
                level="agent",
            ),
            MemoryScope(org_id=scope.org_id, user_id=scope.user_id, level="user"),
        ]
        if scope.team_id:
            scopes.append(MemoryScope(org_id=scope.org_id, team_id=scope.team_id, level="team"))
        scopes.append(MemoryScope(org_id=scope.org_id, level="org"))
        return scopes

    @staticmethod
    def resolve_writable_scope(scope: MemoryScope) -> MemoryScope:
        """Return most-specific writable scope."""
        if scope.agent_id:
            return MemoryScope(
                org_id=scope.org_id,
                team_id=scope.team_id,
                user_id=scope.user_id,
                agent_id=scope.agent_id,
                level="agent",
            )
        if scope.user_id:
            return MemoryScope(
                org_id=scope.org_id,
                team_id=scope.team_id,
                user_id=scope.user_id,
                level="user",
            )
        if scope.team_id:
            return MemoryScope(org_id=scope.org_id, team_id=scope.team_id, level="team")
        return MemoryScope(org_id=scope.org_id, level="org")

    @staticmethod
    def to_sql_filter(
        scopes: list[MemoryScope],
        org_id_col: ColumnElement | None = None,
        team_id_col: ColumnElement | None = None,
        user_id_col: ColumnElement | None = None,
        agent_id_col: ColumnElement | None = None,
    ) -> ColumnElement[bool]:
        """Build OR-of-AND SQLAlchemy filter across readable scopes."""
        if not scopes:
            return false()

        org_col = org_id_col if org_id_col is not None else MemoryFact.org_id
        team_col = team_id_col if team_id_col is not None else MemoryFact.team_id
        user_col = user_id_col if user_id_col is not None else MemoryFact.user_id
        agent_col = agent_id_col if agent_id_col is not None else MemoryFact.agent_id

        conditions: list[ColumnElement[bool]] = []
        for scope in scopes:
            if scope.level == "org":
                conditions.append(
                    and_(
                        org_col == scope.org_id,
                        team_col.is_(None),
                        user_col.is_(None),
                        agent_col.is_(None),
                    )
                )
            elif scope.level == "team":
                conditions.append(
                    and_(
                        org_col == scope.org_id,
                        team_col == scope.team_id,
                        user_col.is_(None),
                        agent_col.is_(None),
                    )
                )
            elif scope.level == "user":
                team_match = team_col == scope.team_id if scope.team_id else team_col.is_(None)
                conditions.append(
                    and_(
                        org_col == scope.org_id,
                        team_match,
                        user_col == scope.user_id,
                        agent_col.is_(None),
                    )
                )
            else:  # agent
                team_match = team_col == scope.team_id if scope.team_id else team_col.is_(None)
                conditions.append(
                    and_(
                        org_col == scope.org_id,
                        team_match,
                        user_col == scope.user_id,
                        agent_col == scope.agent_id,
                    )
                )

        return or_(*conditions)
