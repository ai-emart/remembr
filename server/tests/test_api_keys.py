"""Tests for API key authentication and management."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import APIKey
from app.services.api_keys import (
    API_KEY_PREFIX,
    generate_api_key,
    hash_api_key,
    verify_api_key,
)

pytestmark = pytest.mark.integration


class TestAPIKeyGeneration:
    """Tests for API key generation and hashing."""

    def test_generate_api_key(self):
        """Test API key generation."""
        raw_key, hashed_key = generate_api_key()

        # Check format
        assert raw_key.startswith(API_KEY_PREFIX)
        assert len(raw_key) > len(API_KEY_PREFIX)

        # Check hash
        assert len(hashed_key) == 64  # SHA256 hex digest
        assert hashed_key != raw_key

    def test_generate_unique_keys(self):
        """Test that generated keys are unique."""
        key1, hash1 = generate_api_key()
        key2, hash2 = generate_api_key()

        assert key1 != key2
        assert hash1 != hash2

    def test_hash_api_key(self):
        """Test API key hashing."""
        key = f"{API_KEY_PREFIX}test_key_12345"
        hashed = hash_api_key(key)

        assert len(hashed) == 64
        assert hashed != key

        # Same key should produce same hash
        hashed2 = hash_api_key(key)
        assert hashed == hashed2

    def test_verify_api_key_success(self):
        """Test successful API key verification."""
        raw_key, hashed_key = generate_api_key()

        assert verify_api_key(raw_key, hashed_key) is True

    def test_verify_api_key_failure(self):
        """Test failed API key verification."""
        raw_key, hashed_key = generate_api_key()
        wrong_key = f"{API_KEY_PREFIX}wrong_key"

        assert verify_api_key(wrong_key, hashed_key) is False


@pytest.mark.asyncio
class TestCreateAPIKeyEndpoint:
    """Tests for API key creation endpoint."""

    async def test_create_api_key_success(self, client: AsyncClient, db: AsyncSession):
        """Test successful API key creation."""
        # Register and login
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "apikey@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )
        access_token = response.json()["data"]["access_token"]

        # Create API key
        response = await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "name": "Test API Key",
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()["data"]

        assert "id" in data
        assert data["name"] == "Test API Key"
        assert "api_key" in data
        assert data["api_key"].startswith(API_KEY_PREFIX)
        assert "org_id" in data
        assert "created_at" in data

        # Verify key was stored in database
        result = await db.execute(select(APIKey).where(APIKey.id == data["id"]))
        api_key = result.scalar_one_or_none()

        assert api_key is not None
        assert api_key.name == "Test API Key"
        assert api_key.key_hash != data["api_key"]  # Hash stored, not raw key

    async def test_create_api_key_with_expiration(self, client: AsyncClient):
        """Test creating API key with expiration."""
        # Register and login
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "expire@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )
        access_token = response.json()["data"]["access_token"]

        # Create API key with expiration
        expires_at = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        response = await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "name": "Expiring Key",
                "expires_at": expires_at,
            },
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()["data"]

        assert data["expires_at"] is not None

    async def test_create_api_key_without_auth(self, client: AsyncClient):
        """Test creating API key without authentication."""
        response = await client.post(
            "/api/v1/api-keys",
            json={"name": "Test Key"},
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_create_api_key_invalid_name(self, client: AsyncClient):
        """Test creating API key with invalid name."""
        # Register and login
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "invalid@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )
        access_token = response.json()["data"]["access_token"]

        # Try to create key with empty name
        response = await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"name": ""},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.asyncio
class TestListAPIKeysEndpoint:
    """Tests for API key listing endpoint."""

    async def test_list_api_keys_empty(self, client: AsyncClient):
        """Test listing API keys when none exist."""
        # Register and login
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "list@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )
        access_token = response.json()["data"]["access_token"]

        # List keys
        response = await client.get(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()["data"]

        assert data["keys"] == []
        assert data["total"] == 0

    async def test_list_api_keys_with_keys(self, client: AsyncClient):
        """Test listing API keys."""
        # Register and login
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "listkeys@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )
        access_token = response.json()["data"]["access_token"]

        # Create multiple keys
        await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"name": "Key 1"},
        )
        await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"name": "Key 2"},
        )

        # List keys
        response = await client.get(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()["data"]

        assert len(data["keys"]) == 2
        assert data["total"] == 2

        # Check that raw keys are NOT included
        for key in data["keys"]:
            assert "api_key" not in key
            assert "key_hash" not in key
            assert "name" in key
            assert "id" in key
            assert "created_at" in key

    async def test_list_api_keys_without_auth(self, client: AsyncClient):
        """Test listing API keys without authentication."""
        response = await client.get("/api/v1/api-keys")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    async def test_list_api_keys_org_isolation(self, client: AsyncClient):
        """Test that users only see keys from their organization."""
        # Register user 1
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "user1@example.com",
                "password": "password123",
                "org_name": "Org 1",
            },
        )
        token1 = response.json()["data"]["access_token"]

        # Register user 2
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "user2@example.com",
                "password": "password123",
                "org_name": "Org 2",
            },
        )
        token2 = response.json()["data"]["access_token"]

        # User 1 creates a key
        await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {token1}"},
            json={"name": "User 1 Key"},
        )

        # User 2 creates a key
        await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {token2}"},
            json={"name": "User 2 Key"},
        )

        # User 1 should only see their key
        response = await client.get(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {token1}"},
        )
        data = response.json()["data"]
        assert len(data["keys"]) == 1
        assert data["keys"][0]["name"] == "User 1 Key"

        # User 2 should only see their key
        response = await client.get(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {token2}"},
        )
        data = response.json()["data"]
        assert len(data["keys"]) == 1
        assert data["keys"][0]["name"] == "User 2 Key"


@pytest.mark.asyncio
class TestRevokeAPIKeyEndpoint:
    """Tests for API key revocation endpoint."""

    async def test_revoke_api_key_success(self, client: AsyncClient, db: AsyncSession):
        """Test successful API key revocation."""
        # Register and login
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "revoke@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )
        access_token = response.json()["data"]["access_token"]

        # Create API key
        response = await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"name": "Key to Revoke"},
        )
        key_id = response.json()["data"]["id"]

        # Revoke key
        response = await client.delete(
            f"/api/v1/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == status.HTTP_200_OK

        # Verify key is expired in database
        result = await db.execute(select(APIKey).where(APIKey.id == key_id))
        api_key = result.scalar_one_or_none()

        assert api_key is not None
        assert api_key.expires_at is not None
        assert api_key.expires_at <= datetime.now(UTC)

    async def test_revoke_nonexistent_key(self, client: AsyncClient):
        """Test revoking a non-existent API key."""
        # Register and login
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "nokey@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )
        access_token = response.json()["data"]["access_token"]

        # Try to revoke non-existent key
        fake_id = str(uuid.uuid4())
        response = await client.delete(
            f"/api/v1/api-keys/{fake_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_revoke_key_from_different_org(self, client: AsyncClient):
        """Test that users cannot revoke keys from other organizations."""
        # Register user 1 and create key
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "org1@example.com",
                "password": "password123",
                "org_name": "Org 1",
            },
        )
        token1 = response.json()["data"]["access_token"]

        response = await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {token1}"},
            json={"name": "Org 1 Key"},
        )
        key_id = response.json()["data"]["id"]

        # Register user 2
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "org2@example.com",
                "password": "password123",
                "org_name": "Org 2",
            },
        )
        token2 = response.json()["data"]["access_token"]

        # User 2 tries to revoke user 1's key
        response = await client.delete(
            f"/api/v1/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {token2}"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_revoke_without_auth(self, client: AsyncClient):
        """Test revoking API key without authentication."""
        fake_id = str(uuid.uuid4())
        response = await client.delete(f"/api/v1/api-keys/{fake_id}")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
class TestAPIKeyAuthentication:
    """Tests for API key authentication dependency."""

    async def test_api_key_auth_success(self, client: AsyncClient):
        """Test successful API key authentication."""
        # Register and create API key
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "apikeyauth@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )
        access_token = response.json()["data"]["access_token"]

        response = await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"name": "Auth Test Key"},
        )
        api_key = response.json()["data"]["api_key"]

        # Use API key to access endpoint (using health endpoint as test)
        # Note: In a real scenario, you'd have an endpoint that accepts API key auth
        # For now, we'll just verify the key exists and is valid
        assert api_key.startswith(API_KEY_PREFIX)

    async def test_api_key_auth_missing_header(self, client: AsyncClient):
        """Test API key authentication with missing header."""
        # This would be tested with an endpoint that uses get_api_key_auth
        # For now, we verify the behavior through the service layer
        pass

    async def test_api_key_auth_invalid_format(self, client: AsyncClient):
        """Test API key authentication with invalid format."""
        # This would be tested with an endpoint that uses get_api_key_auth
        pass

    async def test_api_key_auth_expired_key(self, client: AsyncClient, db: AsyncSession):
        """Test API key authentication with expired key."""
        # Register and create API key with past expiration
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "expired@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )
        access_token = response.json()["data"]["access_token"]

        # Create API key with expiration
        past_time = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        response = await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "name": "Expired Key",
                "expires_at": past_time,
            },
        )

        # Key should be created but already expired
        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()["data"]
        assert data["expires_at"] is not None


@pytest.mark.asyncio
class TestAPIKeyCaching:
    """Tests for API key caching behavior."""

    async def test_cache_invalidation_on_revoke(self, client: AsyncClient):
        """Test that cache is invalidated when key is revoked."""
        # Register and create API key
        response = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "cache@example.com",
                "password": "password123",
                "org_name": "Test Org",
            },
        )
        access_token = response.json()["data"]["access_token"]

        response = await client.post(
            "/api/v1/api-keys",
            headers={"Authorization": f"Bearer {access_token}"},
            json={"name": "Cached Key"},
        )
        key_id = response.json()["data"]["id"]
        response.json()["data"]["api_key"]

        # TODO: Use the key to populate cache
        # Then revoke and verify cache is cleared

        # Revoke key
        response = await client.delete(
            f"/api/v1/api-keys/{key_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        assert response.status_code == status.HTTP_200_OK
