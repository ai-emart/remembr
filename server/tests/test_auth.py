"""Tests for authentication endpoints and services."""

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.organization import Organization
from app.models.user import User
from app.services.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

settings = get_settings()


class TestPasswordHashing:
    """Tests for password hashing and verification."""

    def test_hash_password(self):
        """Test password hashing."""
        password = "test_password_123"
        hashed = hash_password(password)

        assert hashed != password
        assert len(hashed) > 0
        assert hashed.startswith("$2b$")

    def test_verify_password_success(self):
        """Test successful password verification."""
        password = "test_password_123"
        hashed = hash_password(password)

        assert verify_password(password, hashed) is True

    def test_verify_password_failure(self):
        """Test failed password verification."""
        password = "test_password_123"
        wrong_password = "wrong_password"
        hashed = hash_password(password)

        assert verify_password(wrong_password, hashed) is False

    def test_different_hashes_for_same_password(self):
        """Test that same password produces different hashes (due to salt)."""
        password = "test_password_123"
        hash1 = hash_password(password)
        hash2 = hash_password(password)

        assert hash1 != hash2
        assert verify_password(password, hash1) is True
        assert verify_password(password, hash2) is True


class TestTokenCreation:
    """Tests for JWT token creation and decoding."""

    def test_create_access_token(self):
        """Test access token creation."""
        data = {"sub": str(uuid.uuid4()), "email": "test@example.com"}
        token = create_access_token(data)

        assert isinstance(token, str)
        assert len(token) > 0

        # Decode and verify
        payload = decode_token(token)
        assert payload["sub"] == data["sub"]
        assert payload["email"] == data["email"]
        assert payload["type"] == "access"
        assert "exp" in payload

    def test_create_refresh_token(self):
        """Test refresh token creation."""
        data = {"sub": str(uuid.uuid4()), "email": "test@example.com"}
        token = create_refresh_token(data)

        assert isinstance(token, str)
        assert len(token) > 0

        # Decode and verify
        payload = decode_token(token)
        assert payload["sub"] == data["sub"]
        assert payload["email"] == data["email"]
        assert payload["type"] == "refresh"
        assert "exp" in payload

    def test_token_expiration_times(self):
        """Test that access and refresh tokens have different expiration times."""
        data = {"sub": str(uuid.uuid4()), "email": "test@example.com"}

        access_token = create_access_token(data)
        refresh_token = create_refresh_token(data)

        access_payload = decode_token(access_token)
        refresh_payload = decode_token(refresh_token)

        access_exp = datetime.fromtimestamp(access_payload["exp"], tz=UTC)
        refresh_exp = datetime.fromtimestamp(refresh_payload["exp"], tz=UTC)

        # Refresh token should expire much later than access token
        assert refresh_exp > access_exp

    def test_decode_invalid_token(self):
        """Test decoding an invalid token."""
        with pytest.raises(Exception):
            decode_token("invalid_token")

    def test_decode_expired_token(self):
        """Test decoding an expired token."""
        data = {"sub": str(uuid.uuid4()), "email": "test@example.com"}

        # Create token that expired 1 hour ago
        expired_time = datetime.now(UTC) - timedelta(hours=1)
        to_encode = data.copy()
        to_encode.update({"exp": expired_time, "type": "access"})

        expired_token = jwt.encode(
            to_encode,
            settings.secret_key.get_secret_value(),
            algorithm=settings.algorithm,
        )

        with pytest.raises(Exception):
            decode_token(expired_token)


@pytest.mark.asyncio
class TestRegisterEndpoint:
    """Tests for user registration endpoint."""

    async def test_register_success(self, client: AsyncClient, db: AsyncSession):
        """Test successful user registration."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "secure_password_123",
                "org_name": "Test Organization",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        json_response = response.json()
        
        # Response is wrapped in StandardResponse format
        assert "data" in json_response
        data = json_response["data"]

        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

        # Verify user was created in database
        result = await db.execute(select(User).where(User.email == "newuser@example.com"))
        user = result.scalar_one_or_none()

        assert user is not None
        assert user.email == "newuser@example.com"
        assert user.is_active is True
        assert user.hashed_password != "secure_password_123"

        # Verify organization was created
        result = await db.execute(select(Organization).where(Organization.id == user.org_id))
        org = result.scalar_one_or_none()

        assert org is not None
        assert org.name == "Test Organization"

    async def test_register_duplicate_email(self, client: AsyncClient, db: AsyncSession):
        """Test registration with duplicate email."""
        # Create first user
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": "duplicate@example.com",
                "password": "password123",
                "org_name": "Org 1",
            },
        )

        # Try to create second user with same email
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "duplicate@example.com",
                "password": "password456",
                "org_name": "Org 2",
            },
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        json_response = response.json()
        assert "error" in json_response
        assert "already registered" in json_response["error"]["message"].lower()

    async def test_register_invalid_email(self, client: AsyncClient):
        """Test registration with invalid email."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "not_an_email",
                "password": "password123",
                "org_name": "Test Org",
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    async def test_register_short_password(self, client: AsyncClient):
        """Test registration with password too short."""
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "test@example.com",
                "password": "short",
                "org_name": "Test Org",
            },
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
class TestLoginEndpoint:
    """Tests for user login endpoint."""

    async def test_login_success(self, client: AsyncClient, db: AsyncSession):
        """Test successful login."""
        # Register user first
        email = "logintest@example.com"
        password = "test_password_123"

        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": password,
                "org_name": "Test Org",
            },
        )

        # Login
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": email,
                "password": password,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        json_response = response.json()
        
        # Response is wrapped in StandardResponse format
        assert "data" in json_response
        data = json_response["data"]

        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, client: AsyncClient):
        """Test login with wrong password."""
        # Register user first
        email = "wrongpass@example.com"

        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "correct_password",
                "org_name": "Test Org",
            },
        )

        # Try to login with wrong password
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": email,
                "password": "wrong_password",
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        json_response = response.json()
        assert "error" in json_response
        assert "incorrect" in json_response["error"]["message"].lower()

    async def test_login_nonexistent_user(self, client: AsyncClient):
        """Test login with non-existent user."""
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": "nonexistent@example.com",
                "password": "password123",
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_login_inactive_user(self, client: AsyncClient, db: AsyncSession):
        """Test login with inactive user."""
        # Register user
        email = "inactive@example.com"
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "password123",
                "org_name": "Test Org",
            },
        )

        # Deactivate user
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        user.is_active = False
        await db.commit()

        # Try to login
        response = await client.post(
            "/api/v1/auth/login",
            json={
                "email": email,
                "password": "password123",
            },
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        json_response = response.json()
        assert "error" in json_response
        assert "inactive" in json_response["error"]["message"].lower()


@pytest.mark.asyncio
class TestRefreshEndpoint:
    """Tests for token refresh endpoint."""

    async def test_refresh_success(self, client: AsyncClient):
        """Test successful token refresh."""
        # Register and get tokens
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "refresh@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )

        refresh_token = response.json()["data"]["refresh_token"]

        # Refresh token
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == status.HTTP_200_OK
        json_response = response.json()
        
        assert "data" in json_response
        data = json_response["data"]

        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert "refresh_token" not in data  # Only returns new access token

    async def test_refresh_with_access_token(self, client: AsyncClient):
        """Test refresh with access token (should fail)."""
        # Register and get tokens
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "wrongtype@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )

        access_token = response.json()["data"]["access_token"]

        # Try to refresh with access token
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": access_token},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_refresh_invalid_token(self, client: AsyncClient):
        """Test refresh with invalid token."""
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "invalid_token"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_refresh_after_logout(self, client: AsyncClient):
        """Test refresh after token has been invalidated."""
        # Register and get tokens
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "logout@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )

        refresh_token = response.json()["data"]["refresh_token"]

        # Logout (invalidate token)
        await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token},
        )

        # Try to refresh with invalidated token
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        json_response = response.json()
        assert "error" in json_response
        assert "invalidated" in json_response["error"]["message"].lower()


@pytest.mark.asyncio
class TestLogoutEndpoint:
    """Tests for logout endpoint."""

    async def test_logout_success(self, client: AsyncClient):
        """Test successful logout."""
        # Register and get tokens
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "logouttest@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )

        refresh_token = response.json()["data"]["refresh_token"]

        # Logout
        response = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": refresh_token},
        )

        assert response.status_code == status.HTTP_200_OK

    async def test_logout_with_access_token(self, client: AsyncClient):
        """Test logout with access token (should fail)."""
        # Register and get tokens
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "logoutwrong@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )

        access_token = response.json()["data"]["access_token"]

        # Try to logout with access token
        response = await client.post(
            "/api/v1/auth/logout",
            json={"refresh_token": access_token},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
class TestMeEndpoint:
    """Tests for current user endpoint."""

    async def test_get_me_success(self, client: AsyncClient):
        """Test getting current user info."""
        # Register and get tokens
        email = "metest@example.com"
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": "password123",
                "org_name": "Test Org",
            },
        )

        access_token = response.json()["data"]["access_token"]

        # Get current user
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == status.HTTP_200_OK
        json_response = response.json()
        
        assert "data" in json_response
        data = json_response["data"]

        assert data["email"] == email
        assert "id" in data
        assert "org_id" in data
        assert "is_active" in data
        assert "created_at" in data
        # Verify it's a dict, not a User model instance
        assert isinstance(data, dict)
        assert "hashed_password" not in data  # Should never be exposed

    async def test_get_me_no_token(self, client: AsyncClient):
        """Test getting current user without token."""
        response = await client.get("/api/v1/auth/me")

        assert response.status_code == status.HTTP_403_FORBIDDEN

    async def test_get_me_invalid_token(self, client: AsyncClient):
        """Test getting current user with invalid token."""
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer invalid_token"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_get_me_with_refresh_token(self, client: AsyncClient):
        """Test getting current user with refresh token (should fail)."""
        # Register and get tokens
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "mewrong@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )

        refresh_token = response.json()["data"]["refresh_token"]

        # Try to access with refresh token
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {refresh_token}"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
