"""Tests for Row-Level Security policy installation and helpers."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

from app import models as _models  # noqa: F401  Registers SQLAlchemy models with Base.metadata.
from app.db.rls import clear_org_context, get_org_context, set_org_context

pytestmark = pytest.mark.integration

RLS_TABLES = {
    "sessions": "sessions_org_isolation",
    "episodes": "episodes_org_isolation",
    "memory_facts": "memory_facts_org_isolation",
    "embeddings": "embeddings_org_isolation",
}


@pytest_asyncio.fixture(autouse=True)
async def install_rls_policies(db):
    """Install the same RLS policies defined in the Alembic migration."""
    for table, policy in RLS_TABLES.items():
        await db.execute(text(f"DROP POLICY IF EXISTS {policy} ON {table}"))
        await db.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
        await db.execute(
            text(
                f"""
                CREATE POLICY {policy} ON {table}
                USING (org_id = current_setting('app.current_org_id', true)::uuid)
                WITH CHECK (org_id = current_setting('app.current_org_id', true)::uuid)
                """
            )
        )
    await db.commit()
    yield


@pytest.mark.asyncio
async def test_set_org_context(db):
    """Setting org context writes the session parameter."""
    org_id = uuid.uuid4()

    await set_org_context(db, org_id)
    current_org = await get_org_context(db)

    assert current_org == str(org_id)


@pytest.mark.asyncio
async def test_clear_org_context(db):
    """Clearing org context removes the session parameter."""
    org_id = uuid.uuid4()

    await set_org_context(db, org_id)
    assert await get_org_context(db) == str(org_id)

    await clear_org_context(db)
    current_org = await get_org_context(db)

    assert current_org is None or current_org == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(("table_name", "policy_name"), list(RLS_TABLES.items()))
async def test_rls_enabled_on_expected_tables(db, table_name: str, policy_name: str):
    """RLS should be enabled for every multi-tenant table."""
    result = await db.execute(
        text(
            """
            SELECT c.relrowsecurity, c.relforcerowsecurity
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = :table_name
            """
        ),
        {"table_name": table_name},
    )
    row = result.one()

    assert row.relrowsecurity is True
    assert row.relforcerowsecurity is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("table_name", "policy_name"), list(RLS_TABLES.items()))
async def test_expected_policies_exist(db, table_name: str, policy_name: str):
    """Each RLS-managed table should have the expected policy name."""
    result = await db.execute(
        text(
            """
            SELECT policyname
            FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = :table_name
              AND policyname = :policy_name
            """
        ),
        {"table_name": table_name, "policy_name": policy_name},
    )

    assert result.scalar_one() == policy_name


@pytest.mark.asyncio
@pytest.mark.parametrize(("table_name", "policy_name"), list(RLS_TABLES.items()))
async def test_policy_uses_current_org_setting(db, table_name: str, policy_name: str):
    """Policy expressions should reference app.current_org_id for both USING and CHECK."""
    result = await db.execute(
        text(
            """
            SELECT qual, with_check
            FROM pg_policies
            WHERE schemaname = 'public'
              AND tablename = :table_name
              AND policyname = :policy_name
            """
        ),
        {"table_name": table_name, "policy_name": policy_name},
    )
    row = result.one()

    assert "current_setting('app.current_org_id'" in row.qual
    assert "current_setting('app.current_org_id'" in row.with_check


@pytest.mark.asyncio
async def test_current_setting_defaults_to_none_when_unset(db):
    """The org context setting should be absent before authentication sets it."""
    result = await db.execute(text("SELECT current_setting('app.current_org_id', true)"))

    assert result.scalar_one_or_none() is None


@pytest.mark.asyncio
async def test_setting_is_transaction_scoped(db):
    """SET LOCAL should not leak across commits."""
    org_id = uuid.uuid4()

    await set_org_context(db, org_id)
    assert await get_org_context(db) == str(org_id)

    await db.commit()

    current_org = await get_org_context(db)
    assert current_org is None or current_org == ""
