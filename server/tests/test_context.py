"""Tests for request context middleware."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.middleware.context import (
    RequestContext,
    get_current_context,
    get_request_context,
    require_auth,
    set_current_context,
)
from app.models.agent import Agent
from app.models.organization import Organization
from app.models.user import User
from app.services.api_keys import create_api_key
from app.services.auth import create_access_token, hash_password

pytestmark = pytest.mark.integration


def _fake_request() -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace())


@pytest_asyncio.fixture
async def test_org(db):
    """Create a test organization."""
    org = Organization(
        id=uuid.uuid4(),
        name="Test Org",
    )
    db.add(org)
    await db.flush()
    return org


@pytest_asyncio.fixture
async def test_user(db, test_org):
    """Create a test user."""
    user = User(
        id=uuid.uuid4(),
        org_id=test_org.id,
        email="test@example.com",
        hashed_password=hash_password("password123"),
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def test_api_key(db, test_org, test_user):
    """Create a test API key."""
    api_key, raw_key = await create_api_key(
        db=db,
        org_id=test_org.id,
        name="Test Key",
        user_id=test_user.id,
    )
    await db.commit()
    return api_key, raw_key


class TestRequestContext:
    """Test RequestContext dataclass."""

    def test_request_context_creation(self):
        """Test creating a RequestContext."""
        ctx = RequestContext(
            request_id="test-123",
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            agent_id=None,
            auth_method="jwt",
        )

        assert ctx.request_id == "test-123"
        assert ctx.auth_method == "jwt"
        assert ctx.agent_id is None

    def test_request_context_repr(self):
        """Test RequestContext string representation."""
        org_id = uuid.uuid4()
        user_id = uuid.uuid4()

        ctx = RequestContext(
            request_id="test-123",
            org_id=org_id,
            user_id=user_id,
            agent_id=None,
            auth_method="api_key",
        )

        repr_str = repr(ctx)
        assert "test-123" in repr_str
        assert str(org_id) in repr_str
        assert str(user_id) in repr_str
        assert "api_key" in repr_str


class TestContextVars:
    """Test contextvars functionality."""

    def test_get_set_context(self):
        """Test getting and setting context."""
        ctx = RequestContext(
            request_id="test-123",
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            agent_id=None,
            auth_method="jwt",
        )

        # Initially None
        assert get_current_context() is None

        # Set context
        set_current_context(ctx)

        # Should be retrievable
        retrieved = get_current_context()
        assert retrieved is not None
        assert retrieved.request_id == "test-123"
        assert retrieved.auth_method == "jwt"


@pytest.mark.asyncio
class TestJWTAuth:
    """Test JWT authentication in context middleware."""

    async def test_jwt_auth_success(self, db, test_user):
        """Test successful JWT authentication."""
        # Create access token
        token = create_access_token(
            {
                "sub": str(test_user.id),
                "email": test_user.email,
            }
        )

        # Mock dependencies
        from fastapi.security import HTTPAuthorizationCredentials

        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=token,
        )

        # Mock Redis
        redis_mock = AsyncMock()

        # Call get_request_context
        from app.middleware.context import get_request_context

        context = await get_request_context(
            request=_fake_request(),
            credentials=credentials,
            x_api_key=None,
            db=db,
            redis=redis_mock,
        )

        # Verify context
        assert context is not None
        assert context.org_id == test_user.org_id
        assert context.user_id == test_user.id
        assert context.auth_method == "jwt"
        assert context.agent_id is None

    async def test_jwt_auth_with_agent_id(self, db, test_user):
        """Test JWT authentication with agent_id in token."""
        agent_id = uuid.uuid4()

        # Create access token with agent_id
        token = create_access_token(
            {
                "sub": str(test_user.id),
                "email": test_user.email,
                "agent_id": str(agent_id),
            }
        )

        from fastapi.security import HTTPAuthorizationCredentials

        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=token,
        )

        redis_mock = AsyncMock()

        context = await get_request_context(
            request=_fake_request(),
            credentials=credentials,
            x_api_key=None,
            db=db,
            redis=redis_mock,
        )

        assert context is not None
        assert context.agent_id == agent_id

    async def test_jwt_auth_inactive_user(self, db, test_user):
        """Test JWT authentication with inactive user."""
        # Deactivate user
        test_user.is_active = False
        await db.commit()

        # Create token
        token = create_access_token(
            {
                "sub": str(test_user.id),
                "email": test_user.email,
            }
        )

        from fastapi.security import HTTPAuthorizationCredentials

        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=token,
        )

        redis_mock = AsyncMock()

        context = await get_request_context(
            request=_fake_request(),
            credentials=credentials,
            x_api_key=None,
            db=db,
            redis=redis_mock,
        )

        # Should return None for inactive user
        assert context is None

    async def test_jwt_auth_invalid_token(self, db):
        """Test JWT authentication with invalid token."""
        from fastapi.security import HTTPAuthorizationCredentials

        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="invalid.token.here",
        )

        redis_mock = AsyncMock()

        context = await get_request_context(
            request=_fake_request(),
            credentials=credentials,
            x_api_key=None,
            db=db,
            redis=redis_mock,
        )

        # Should return None for invalid token
        assert context is None

    async def test_jwt_auth_user_not_found(self, db):
        """Test JWT authentication with non-existent user."""
        # Create token for non-existent user
        fake_user_id = uuid.uuid4()
        token = create_access_token(
            {
                "sub": str(fake_user_id),
                "email": "fake@example.com",
            }
        )

        from fastapi.security import HTTPAuthorizationCredentials

        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=token,
        )

        redis_mock = AsyncMock()

        context = await get_request_context(
            request=_fake_request(),
            credentials=credentials,
            x_api_key=None,
            db=db,
            redis=redis_mock,
        )

        # Should return None for non-existent user
        assert context is None


@pytest.mark.asyncio
class TestAPIKeyAuth:
    """Test API key authentication in context middleware."""

    async def test_api_key_auth_success(self, db, test_org, test_user):
        """Test successful API key authentication."""
        # Create API key
        api_key, raw_key = await create_api_key(
            db=db,
            org_id=test_org.id,
            name="Test Key",
            user_id=test_user.id,
        )
        await db.commit()

        # Mock Redis
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None  # Cache miss
        redis_mock.setex.return_value = True

        context = await get_request_context(
            request=_fake_request(),
            credentials=None,
            x_api_key=raw_key,
            db=db,
            redis=redis_mock,
        )

        # Verify context
        assert context is not None
        assert context.org_id == test_org.id
        assert context.user_id == test_user.id
        assert context.auth_method == "api_key"

    async def test_api_key_auth_with_agent(self, db, test_org):
        """Test API key authentication with agent_id."""
        agent = Agent(
            id=uuid.uuid4(),
            org_id=test_org.id,
            name="Agent Key Owner",
        )
        db.add(agent)
        await db.flush()

        # Create API key with agent_id
        api_key, raw_key = await create_api_key(
            db=db,
            org_id=test_org.id,
            name="Agent Key",
            agent_id=agent.id,
        )
        await db.commit()

        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        redis_mock.setex.return_value = True

        context = await get_request_context(
            request=_fake_request(),
            credentials=None,
            x_api_key=raw_key,
            db=db,
            redis=redis_mock,
        )

        assert context is not None
        assert context.agent_id == agent.id
        assert context.user_id is None

    async def test_api_key_auth_invalid_key(self, db):
        """Test API key authentication with invalid key."""
        redis_mock = AsyncMock()
        redis_mock.get.return_value = None

        context = await get_request_context(
            request=_fake_request(),
            credentials=None,
            x_api_key="rmbr_invalid_key_12345678901234",
            db=db,
            redis=redis_mock,
        )

        # Should return None for invalid key
        assert context is None

    async def test_api_key_auth_expired_key(self, db, test_org):
        """Test API key authentication with expired key."""
        # Create expired API key
        api_key, raw_key = await create_api_key(
            db=db,
            org_id=test_org.id,
            name="Expired Key",
            expires_at=datetime.now(UTC) - timedelta(days=1),
        )
        await db.commit()

        redis_mock = AsyncMock()
        redis_mock.get.return_value = None

        context = await get_request_context(
            request=_fake_request(),
            credentials=None,
            x_api_key=raw_key,
            db=db,
            redis=redis_mock,
        )

        # Should return None for expired key
        assert context is None


@pytest.mark.asyncio
class TestAuthFallback:
    """Test authentication fallback behavior."""

    async def test_jwt_fallback_to_api_key(self, db, test_org, test_user):
        """Test that invalid JWT falls back to API key."""
        # Create API key
        api_key, raw_key = await create_api_key(
            db=db,
            org_id=test_org.id,
            name="Fallback Key",
            user_id=test_user.id,
        )
        await db.commit()

        # Provide invalid JWT and valid API key
        from fastapi.security import HTTPAuthorizationCredentials

        credentials = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="invalid.jwt.token",
        )

        redis_mock = AsyncMock()
        redis_mock.get.return_value = None
        redis_mock.setex.return_value = True

        context = await get_request_context(
            request=_fake_request(),
            credentials=credentials,
            x_api_key=raw_key,
            db=db,
            redis=redis_mock,
        )

        # Should succeed with API key
        assert context is not None
        assert context.auth_method == "api_key"

    async def test_no_auth_returns_none(self, db):
        """Test that no authentication returns None."""
        redis_mock = AsyncMock()

        context = await get_request_context(
            request=_fake_request(),
            credentials=None,
            x_api_key=None,
            db=db,
            redis=redis_mock,
        )

        assert context is None


@pytest.mark.asyncio
class TestRequireAuth:
    """Test require_auth dependency."""

    async def test_require_auth_with_valid_context(self):
        """Test require_auth with valid context."""
        ctx = RequestContext(
            request_id="test-123",
            org_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            agent_id=None,
            auth_method="jwt",
        )

        result = await require_auth(context=ctx)

        assert result == ctx

    async def test_require_auth_without_context(self):
        """Test require_auth without context raises 401."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await require_auth(context=None)

        assert exc_info.value.status_code == 401
        assert "Authentication required" in exc_info.value.detail


@pytest.mark.asyncio
class TestIntegration:
    """Integration tests with FastAPI app."""

    async def test_protected_endpoint_with_jwt(self, db, test_user):
        """Test protected endpoint with JWT authentication."""
        # Create test app
        app = FastAPI()
        from app.middleware.context import get_request_context

        @app.get("/protected")
        async def protected_route(
            ctx: RequestContext = Depends(require_auth),
        ):
            return {
                "org_id": str(ctx.org_id),
                "user_id": str(ctx.user_id),
                "auth_method": ctx.auth_method,
            }

        # Create token
        token = create_access_token(
            {
                "sub": str(test_user.id),
                "email": test_user.email,
            }
        )

        # Test with client
        client = TestClient(app)

        async def _override_context():
            return RequestContext(
                request_id="req-test",
                org_id=test_user.org_id,
                user_id=test_user.id,
                agent_id=None,
                auth_method="jwt",
            )

        app.dependency_overrides[get_request_context] = _override_context
        response = client.get("/protected", headers={"Authorization": f"Bearer {token}"})

        assert response.status_code == 200
        data = response.json()
        assert data["org_id"] == str(test_user.org_id)
        assert data["user_id"] == str(test_user.id)
        assert data["auth_method"] == "jwt"

    async def test_protected_endpoint_without_auth(self):
        """Test protected endpoint without authentication."""
        app = FastAPI()
        from app.middleware.context import get_request_context

        @app.get("/protected")
        async def protected_route(
            ctx: RequestContext = Depends(require_auth),
        ):
            return {"message": "success"}

        client = TestClient(app)

        async def _override_context():
            return None

        app.dependency_overrides[get_request_context] = _override_context
        response = client.get("/protected")

        assert response.status_code == 401
