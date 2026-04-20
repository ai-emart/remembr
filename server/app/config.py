from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: SecretStr = Field(
        ...,
        description="PostgreSQL connection string with pgvector support",
    )

    # Redis
    redis_url: SecretStr = Field(
        ...,
        description="Redis connection string (Upstash)",
    )

    # JWT Authentication
    secret_key: SecretStr = Field(
        ...,
        description="Secret key for JWT token signing",
    )
    algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm",
    )
    access_token_expire_minutes: int = Field(
        default=30,
        description="Access token expiration time in minutes",
    )
    refresh_token_expire_days: int = Field(
        default=7,
        description="Refresh token expiration time in days",
    )

    # Monitoring
    sentry_dsn: SecretStr | None = Field(
        default=None,
        description="Sentry DSN for error tracking (optional)",
    )

    # Environment
    environment: Literal["local", "staging", "production"] = Field(
        default="local",
        description="Deployment environment",
    )

    # Embedding provider selection
    embedding_provider: Literal["jina", "ollama", "openai", "sentence_transformers"] = Field(
        default="sentence_transformers",
        description="Embedding backend to use",
    )

    # Jina AI (optional — only required when embedding_provider=jina)
    jina_api_key: SecretStr | None = Field(
        default=None,
        description="Jina AI API key (required when embedding_provider=jina)",
    )
    jina_embedding_model: str = Field(
        default="jina-embeddings-v3",
        description="Jina embedding model to use",
    )

    # Ollama (local)
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Ollama server base URL",
    )
    ollama_embedding_model: str = Field(
        default="nomic-embed-text",
        description="Ollama embedding model to use",
    )

    # OpenAI (optional — only required when embedding_provider=openai)
    openai_api_key: SecretStr | None = Field(
        default=None,
        description="OpenAI API key (required when embedding_provider=openai)",
    )
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model to use",
    )

    # Sentence-Transformers (local, no API key needed)
    sentence_transformers_model: str = Field(
        default="all-MiniLM-L6-v2",
        description="Sentence-Transformers model name",
    )

    embedding_batch_size: int = Field(
        default=100,
        description="Batch size for embedding generation",
    )

    # Short-term memory
    short_term_max_tokens: int = Field(
        default=4000,
        description="Max token budget for short-term sliding window",
    )
    short_term_auto_checkpoint_threshold: float = Field(
        default=0.8,
        description="Threshold ratio to trigger automatic short-term checkpointing",
    )

    # Logging
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)",
    )

    cors_origins: list[str] = Field(
        default_factory=list,
        description="Allowed CORS origins",
    )

    # Rate limiting
    rate_limit_default_per_minute: int = Field(
        default=100,
        description="Default request rate limit per minute per API key/token",
    )
    rate_limit_search_per_minute: int = Field(
        default=30,
        description="Memory search endpoint rate limit per minute per API key/token",
    )

    # DB pool tuning
    db_pool_size: int = Field(default=10, description="Async DB connection pool size")
    db_max_overflow: int = Field(default=20, description="Async DB pool overflow")
    db_pool_timeout: int = Field(default=30, description="Async DB pool timeout in seconds")
    db_pool_recycle: int = Field(default=1800, description="Async DB pool recycle time in seconds")

    # API Configuration
    api_v1_prefix: str = Field(
        default="/api/v1",
        description="API v1 route prefix",
    )

    @field_validator("short_term_auto_checkpoint_threshold")
    @classmethod
    def validate_short_term_auto_checkpoint_threshold(cls, v: float) -> float:
        """Validate auto-checkpoint threshold is in the open interval (0, 1]."""
        if v <= 0 or v > 1:
            raise ValueError("short_term_auto_checkpoint_threshold must be in (0, 1]")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate log level is a valid option."""
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v_upper = v.upper()
        if v_upper not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v_upper

    @field_validator("rate_limit_default_per_minute", "rate_limit_search_per_minute")
    @classmethod
    def validate_rate_limits(cls, v: int) -> int:
        if v < 1:
            raise ValueError("rate limits must be >= 1")
        return v

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.environment == "production"

    @property
    def is_local(self) -> bool:
        """Check if running in local environment."""
        return self.environment == "local"


@lru_cache
def get_settings() -> Settings:
    """
    Get cached settings instance.

    Settings are loaded once and cached for the application lifetime.
    """
    return Settings()


def get_test_settings() -> Settings:
    """
    Get settings for testing with overridden database URL.

    Uses a separate test database to avoid polluting production data.
    """
    settings = get_settings()

    # Override database URL for testing - handle both /remembr and /remembr_test
    db_url = settings.database_url.get_secret_value()
    if "/remembr_test" not in db_url:
        test_db_url = db_url.replace("/remembr", "/remembr_test")
    else:
        test_db_url = db_url

    return Settings(
        database_url=SecretStr(test_db_url),
        redis_url=settings.redis_url,
        secret_key=settings.secret_key,
        environment="local",
        log_level="DEBUG",
    )
