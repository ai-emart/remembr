"""Tests for the dev-only admin UI."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

# Ensure env vars are present before importing the app
os.environ.setdefault("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5433/remembr_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-admin-tests")
os.environ.setdefault("JINA_API_KEY", "test-jina-key")
os.environ.setdefault("ENVIRONMENT", "local")

from app.main import create_app

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
_ORG_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
_SESS_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
_EP_ID = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


def _fake_org():
    org = MagicMock()
    org.id = _ORG_ID
    org.name = "Test Org"
    return org


def _fake_session_row():
    s = MagicMock()
    s.id = _SESS_ID
    s.created_at = _NOW
    s.updated_at = _NOW
    s.metadata_ = {}
    row = MagicMock()
    row.Session = s
    row.message_count = 3
    row.last_activity = _NOW
    return row


def _fake_episode():
    ep = MagicMock()
    ep.id = _EP_ID
    ep.role = "user"
    ep.content = "hello world"
    ep.tags = ["test"]
    ep.created_at = _NOW
    ep.embedding_status = "ready"
    ep.session_id = _SESS_ID
    return ep


def _make_db_mock(org=True, sessions=True, episodes=True):
    """Return an AsyncSession mock with realistic scalar results."""
    db = AsyncMock()

    async def fake_execute(query):
        result = MagicMock()
        # Organization lookup
        result.scalar_one_or_none.return_value = _fake_org() if org else None
        result.scalar_one.return_value = 1
        # Sessions list
        result.all.return_value = [_fake_session_row()] if sessions else []
        # Episodes list
        result.scalars.return_value.all.return_value = [_fake_episode()] if episodes else []
        return result

    db.execute = fake_execute
    return db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_app():
    return create_app()


@pytest.fixture
def local_client(admin_app):
    """TestClient — Starlette uses 'testclient' as client host (whitelisted)."""
    return TestClient(admin_app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# 1. Localhost guard
# ---------------------------------------------------------------------------

def test_admin_rejects_non_localhost():
    """The localhost guard raises 403 for external IPs."""
    from fastapi import HTTPException
    from app.admin.router import _guard

    mock_req = MagicMock()
    mock_req.client = MagicMock()
    mock_req.client.host = "10.0.0.1"

    with pytest.raises(HTTPException) as exc_info:
        _guard(mock_req)
    assert exc_info.value.status_code == 403


def test_admin_allows_testclient_host(local_client):
    """TestClient host 'testclient' is whitelisted — should not 403."""
    with patch("app.admin.router.get_db") as mock_get_db:
        db = _make_db_mock()
        mock_get_db.return_value = db

        async def override():
            yield db

        from app.db.session import get_db
        from app.admin.router import router  # noqa: F401

        # We just check the 403 is NOT returned
        # (may 500 if DB isn't real, that's OK for this test)
        response = local_client.get("/admin")
        assert response.status_code != 403


# ---------------------------------------------------------------------------
# 2. Production guard — admin router must not be mounted in production
# ---------------------------------------------------------------------------

def test_admin_not_available_in_production():
    """Admin router must not be registered when environment=production."""
    from app.config import get_settings

    with patch.dict(os.environ, {"ENVIRONMENT": "production"}):
        get_settings.cache_clear()
        try:
            prod_app = create_app()
            client = TestClient(prod_app, raise_server_exceptions=False)
            response = client.get("/admin")
            assert response.status_code == 404
        finally:
            get_settings.cache_clear()
            os.environ["ENVIRONMENT"] = "local"
            get_settings.cache_clear()


# ---------------------------------------------------------------------------
# 3. Basic rendering — each page returns 200 + key HTML markers
# ---------------------------------------------------------------------------

def _patched_client(admin_app):
    """Return a TestClient with the DB dependency overridden."""
    from app.db.session import get_db

    db = _make_db_mock()

    async def override_db():
        yield db

    admin_app.dependency_overrides[get_db] = override_db
    client = TestClient(admin_app, raise_server_exceptions=False)
    return client, admin_app


def test_sessions_page_renders(admin_app):
    client, app = _patched_client(admin_app)
    try:
        response = client.get("/admin")
        assert response.status_code == 200
        assert "Sessions" in response.text
        assert "Remembr Admin" in response.text
    finally:
        app.dependency_overrides.clear()


def test_sessions_page_shows_session_row(admin_app):
    client, app = _patched_client(admin_app)
    try:
        response = client.get("/admin/sessions")
        assert response.status_code == 200
        # Short ID snippet appears in the table
        assert str(_SESS_ID)[:8] in response.text
    finally:
        app.dependency_overrides.clear()


def test_session_detail_renders_memories(admin_app):
    client, app = _patched_client(admin_app)
    try:
        response = client.get(f"/admin/sessions/{_SESS_ID}")
        assert response.status_code == 200
        assert "hello world" in response.text
        assert "user" in response.text
    finally:
        app.dependency_overrides.clear()


def test_search_page_renders(admin_app):
    client, app = _patched_client(admin_app)
    try:
        response = client.get("/admin/search")
        assert response.status_code == 200
        assert "Search Memories" in response.text
        assert "<form" in response.text
    finally:
        app.dependency_overrides.clear()


def test_health_page_renders(admin_app):
    client, app = _patched_client(admin_app)
    try:
        with patch("app.admin.router._get_health_data") as mock_health:
            mock_health.return_value = {
                "pg_ok": True,
                "pg_error": "",
                "redis_ok": True,
                "redis_error": "",
                "embedding_provider": "sentence_transformers",
                "environment": "local",
            }
            response = client.get("/admin/health")
        assert response.status_code == 200
        assert "Health" in response.text
        assert "PostgreSQL" in response.text
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 4. HTMX fragment endpoints return HTML, not JSON
# ---------------------------------------------------------------------------

def test_session_detail_returns_html_not_json(admin_app):
    """GET /admin/sessions/{id} must return HTML fragment."""
    client, app = _patched_client(admin_app)
    try:
        response = client.get(f"/admin/sessions/{_SESS_ID}")
        assert response.status_code == 200
        ct = response.headers.get("content-type", "")
        assert "html" in ct
        assert response.text.strip().startswith("<")
    finally:
        app.dependency_overrides.clear()


def test_memories_more_returns_html_fragment(admin_app):
    """GET /admin/sessions/{id}/memories returns HTML rows, not JSON."""
    client, app = _patched_client(admin_app)
    try:
        response = client.get(f"/admin/sessions/{_SESS_ID}/memories?offset=0")
        assert response.status_code == 200
        ct = response.headers.get("content-type", "")
        assert "html" in ct
    finally:
        app.dependency_overrides.clear()


def test_search_post_returns_html_fragment(admin_app):
    """POST /admin/search returns an HTML fragment (not JSON)."""
    client, app = _patched_client(admin_app)
    try:
        response = client.post(
            "/admin/search",
            data={"query": "hello", "session_filter": "", "tag_filter": ""},
        )
        assert response.status_code == 200
        ct = response.headers.get("content-type", "")
        assert "html" in ct
    finally:
        app.dependency_overrides.clear()


def test_health_htmx_request_returns_fragment(admin_app):
    """GET /admin/health with hx-request header returns fragment without full page."""
    client, app = _patched_client(admin_app)
    try:
        with patch("app.admin.router._get_health_data") as mock_health:
            mock_health.return_value = {
                "pg_ok": False,
                "pg_error": "Connection refused",
                "redis_ok": False,
                "redis_error": "Connection refused",
                "embedding_provider": "jina",
                "environment": "local",
            }
            response = client.get("/admin/health", headers={"hx-request": "true"})
        assert response.status_code == 200
        # Fragment should not include the full <html> wrapper
        assert "<html" not in response.text
        assert "health-cards" in response.text
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# 5. Org resolution — X-Admin-Org-ID header
# ---------------------------------------------------------------------------

def test_custom_org_id_header_is_used(admin_app):
    """When X-Admin-Org-ID is provided, it must be passed to DB queries."""
    from app.db.session import get_db

    captured_queries: list[str] = []

    db = AsyncMock()

    async def capturing_execute(query):
        captured_queries.append(str(query))
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalar_one.return_value = 0
        result.all.return_value = []
        result.scalars.return_value.all.return_value = []
        return result

    db.execute = capturing_execute

    async def override_db():
        yield db

    admin_app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(admin_app, raise_server_exceptions=False)
        # Provide a custom org ID — endpoint should use it (not query for first org)
        response = client.get(
            "/admin",
            headers={"X-Admin-Org-ID": str(_ORG_ID)},
        )
        # No SELECT on organizations table expected (we gave the header)
        org_queries = [q for q in captured_queries if "organizations" in q.lower()]
        assert len(org_queries) == 0, "Should not have queried organizations table when header provided"
    finally:
        admin_app.dependency_overrides.clear()
