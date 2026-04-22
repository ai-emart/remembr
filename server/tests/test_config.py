"""Tests for configuration module."""

import pytest
from pydantic import SecretStr, ValidationError

from app.config import Settings

def test_settings_validation(monkeypatch: pytest.MonkeyPatch):
    """Test that Settings validates required fields when env file loading is disabled."""
    for key in ("DATABASE_URL", "REDIS_URL", "SECRET_KEY"):
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None)

    message = str(exc_info.value)
    assert "database_url" in message
    assert "redis_url" in message
    assert "secret_key" in message


def test_settings_with_valid_data():
    """Test Settings with valid configuration."""
    settings = Settings(
        database_url=SecretStr("postgresql://localhost/test"),
        redis_url=SecretStr("redis://localhost:6379"),
        secret_key=SecretStr("test-secret-key"),
        jina_api_key=SecretStr("test-jina-key"),
    )

    assert settings.database_url.get_secret_value() == "postgresql://localhost/test"
    assert settings.redis_url.get_secret_value() == "redis://localhost:6379"
    assert settings.algorithm == "HS256"
    assert settings.access_token_expire_minutes == 30
    assert settings.environment == "local"


def test_settings_log_level_validation():
    """Test that log level is validated."""
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            database_url=SecretStr("postgresql://localhost/test"),
            redis_url=SecretStr("redis://localhost:6379"),
            secret_key=SecretStr("test-secret-key"),
            jina_api_key=SecretStr("test-jina-key"),
            log_level="INVALID",
        )

    assert "log_level" in str(exc_info.value)


def test_settings_log_level_case_insensitive():
    """Test that log level accepts lowercase."""
    settings = Settings(
        database_url=SecretStr("postgresql://localhost/test"),
        redis_url=SecretStr("redis://localhost:6379"),
        secret_key=SecretStr("test-secret-key"),
        jina_api_key=SecretStr("test-jina-key"),
        log_level="debug",
    )

    assert settings.log_level == "DEBUG"


def test_settings_environment_validation():
    """Test that environment is validated."""
    with pytest.raises(ValidationError):
        Settings(
            database_url=SecretStr("postgresql://localhost/test"),
            redis_url=SecretStr("redis://localhost:6379"),
            secret_key=SecretStr("test-secret-key"),
            jina_api_key=SecretStr("test-jina-key"),
            environment="invalid",
        )


def test_settings_is_production():
    """Test is_production property."""
    settings = Settings(
        database_url=SecretStr("postgresql://localhost/test"),
        redis_url=SecretStr("redis://localhost:6379"),
        secret_key=SecretStr("test-secret-key"),
        jina_api_key=SecretStr("test-jina-key"),
        environment="production",
    )

    assert settings.is_production is True
    assert settings.is_local is False


def test_settings_is_local():
    """Test is_local property."""
    settings = Settings(
        database_url=SecretStr("postgresql://localhost/test"),
        redis_url=SecretStr("redis://localhost:6379"),
        secret_key=SecretStr("test-secret-key"),
        jina_api_key=SecretStr("test-jina-key"),
        environment="local",
    )

    assert settings.is_local is True
    assert settings.is_production is False


def test_settings_optional_sentry_dsn():
    """Test that sentry_dsn is optional."""
    settings = Settings(
        database_url=SecretStr("postgresql://localhost/test"),
        redis_url=SecretStr("redis://localhost:6379"),
        secret_key=SecretStr("test-secret-key"),
        jina_api_key=SecretStr("test-jina-key"),
    )

    # In test environment, sentry_dsn might be empty string from .env
    # Both None and empty string are acceptable for optional field
    assert settings.sentry_dsn is None or settings.sentry_dsn.get_secret_value() == ""


def test_settings_with_sentry_dsn():
    """Test Settings with Sentry DSN configured."""
    settings = Settings(
        database_url=SecretStr("postgresql://localhost/test"),
        redis_url=SecretStr("redis://localhost:6379"),
        secret_key=SecretStr("test-secret-key"),
        jina_api_key=SecretStr("test-jina-key"),
        sentry_dsn=SecretStr("https://example@sentry.io/123"),
    )

    assert settings.sentry_dsn is not None
    assert "sentry.io" in settings.sentry_dsn.get_secret_value()
