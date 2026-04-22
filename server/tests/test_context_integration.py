"""Integration tests for context middleware with real endpoints."""

import uuid

import pytest
from httpx import AsyncClient

import pytest_asyncio
from app.models.organization import Organization
from app.models.user import User
from app.services.api_keys import create_api_key
from app.services.auth import create_access_token, hash_password

pytestmark = pytest.mark.integration


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


@pytest.mark.asyncio
class TestContextIntegration:
    """Integration tests for context middleware."""

    async def test_me_endpoint_with_jwt(self, client: AsyncClient, test_user):
        """Test /me endpoint with JWT authentication."""
        # Create JWT token
        token = create_access_token(
            {
                "sub": str(test_user.id),
                "email": test_user.email,
            }
        )

        # Call /me endpoint
        response = await client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        payload = data["data"]

        assert payload["org_id"] == str(test_user.org_id)
        assert payload["user_id"] == str(test_user.id)
        assert payload["agent_id"] is None
        assert payload["auth_method"] == "jwt"
        assert "request_id" in data

    async def test_me_endpoint_with_jwt_and_agent(self, client: AsyncClient, test_user):
        """Test /me endpoint with JWT containing agent_id."""
        agent_id = uuid.uuid4()

        # Create JWT token with agent_id
        token = create_access_token(
            {
                "sub": str(test_user.id),
                "email": test_user.email,
                "agent_id": str(agent_id),
            }
        )

        response = await client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()["data"]

        assert data["agent_id"] == str(agent_id)

    async def test_me_endpoint_with_api_key(
        self,
        client: AsyncClient,
        db,
        test_org,
        test_user,
    ):
        """Test /me endpoint with API key authentication."""
        # Create API key
        api_key, raw_key = await create_api_key(
            db=db,
            org_id=test_org.id,
            name="Test Key",
            user_id=test_user.id,
        )
        await db.commit()

        # Call /me endpoint
        response = await client.get(
            "/api/v1/me",
            headers={"X-API-Key": raw_key},
        )

        assert response.status_code == 200
        data = response.json()["data"]

        assert data["org_id"] == str(test_org.id)
        assert data["user_id"] == str(test_user.id)
        assert data["auth_method"] == "api_key"

    async def test_me_endpoint_without_auth(self, client: AsyncClient):
        """Test /me endpoint without authentication."""
        response = await client.get("/api/v1/me")

        assert response.status_code == 401
        data = response.json()

        assert "error" in data
        assert "Authentication required" in data["error"]["message"]

    async def test_me_endpoint_with_invalid_jwt(self, client: AsyncClient):
        """Test /me endpoint with invalid JWT."""
        response = await client.get(
            "/api/v1/me",
            headers={"Authorization": "Bearer invalid.jwt.token"},
        )

        assert response.status_code == 401

    async def test_me_endpoint_with_invalid_api_key(self, client: AsyncClient):
        """Test /me endpoint with invalid API key."""
        response = await client.get(
            "/api/v1/me",
            headers={"X-API-Key": "rmbr_invalid_key_12345678901234"},
        )

        assert response.status_code == 401

    async def test_health_endpoint_no_auth_required(self, client: AsyncClient):
        """Test health endpoint doesn't require authentication."""
        response = await client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()["data"]

        assert data["status"] == "ok"
        assert "version" in data

    async def test_response_headers(self, client: AsyncClient, test_user):
        """Test that response includes context headers."""
        token = create_access_token(
            {
                "sub": str(test_user.id),
                "email": test_user.email,
            }
        )

        response = await client.get(
            "/api/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200

        # Check headers
        assert "X-Request-ID" in response.headers
        assert "X-Org-ID" in response.headers
        assert response.headers["X-Org-ID"] == str(test_user.org_id)

    async def test_jwt_fallback_to_api_key(
        self,
        client: AsyncClient,
        db,
        test_org,
        test_user,
    ):
        """Test that invalid JWT falls back to API key."""
        # Create API key
        api_key, raw_key = await create_api_key(
            db=db,
            org_id=test_org.id,
            name="Fallback Key",
            user_id=test_user.id,
        )
        await db.commit()

        # Provide both invalid JWT and valid API key
        response = await client.get(
            "/api/v1/me",
            headers={
                "Authorization": "Bearer invalid.jwt.token",
                "X-API-Key": raw_key,
            },
        )

        assert response.status_code == 200
        data = response.json()["data"]

        # Should authenticate with API key
        assert data["auth_method"] == "api_key"
        assert data["org_id"] == str(test_org.id)
