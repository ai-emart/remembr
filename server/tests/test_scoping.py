"""Unit tests for memory scope resolution and SQL filter generation."""

import uuid

from sqlalchemy import Column
from sqlalchemy.dialects import postgresql

from app.middleware.context import RequestContext
from app.services.scoping import MemoryScope, ScopeResolver


def _id() -> str:
    return str(uuid.uuid4())


def test_agent_scoped_request_can_read_all_levels() -> None:
    scope = MemoryScope(
        org_id=_id(),
        team_id=_id(),
        user_id=_id(),
        agent_id=_id(),
        level="agent",
    )

    readable = ScopeResolver.resolve_readable_scopes(scope)

    assert [s.level for s in readable] == ["agent", "user", "team", "org"]


def test_user_scoped_request_cannot_read_agent_private_memories() -> None:
    scope = MemoryScope(
        org_id=_id(),
        team_id=_id(),
        user_id=_id(),
        level="user",
    )

    readable = ScopeResolver.resolve_readable_scopes(scope)

    assert [s.level for s in readable] == ["user", "team", "org"]
    assert all(s.agent_id is None for s in readable)


def test_to_sql_filter_generates_or_filter_for_readable_scopes() -> None:
    scope = MemoryScope(
        org_id=_id(),
        team_id=_id(),
        user_id=_id(),
        agent_id=_id(),
        level="agent",
    )
    readable = ScopeResolver.resolve_readable_scopes(scope)

    org_col = Column("org_id", postgresql.UUID(as_uuid=False))
    team_col = Column("team_id", postgresql.UUID(as_uuid=False))
    user_col = Column("user_id", postgresql.UUID(as_uuid=False))
    agent_col = Column("agent_id", postgresql.UUID(as_uuid=False))

    clause = ScopeResolver.to_sql_filter(readable, org_col, team_col, user_col, agent_col)

    # Compile the clause to SQL string
    compiled = str(
        clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )

    # Verify the SQL contains expected elements
    assert " OR " in compiled
    assert "agent_id" in compiled
    assert compiled.count("org_id") >= 4


def test_from_request_context_selects_most_specific_level() -> None:
    ctx = RequestContext(
        request_id="req-1",
        org_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        auth_method="api_key",
    )

    scope = ScopeResolver.from_request_context(ctx)

    assert scope.level == "agent"
    assert scope.org_id == str(ctx.org_id)
