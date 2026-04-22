"""Request context middleware for multi-tenant authentication."""

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.redis import get_redis
from app.db.session import get_db
from app.models.user import User
from app.services.api_keys import lookup_api_key
from app.services.auth import decode_token

# Context variables for request-scoped data (async-safe)
_request_context_var: ContextVar["RequestContext | None"] = ContextVar(
    "request_context", default=None
)

# Optional security for JWT (doesn't raise if missing)
security = HTTPBearer(auto_error=False)


@dataclass
class RequestContext:
    """
    Request-scoped context containing authentication and tenant information.

    This context is stored in contextvars and accessible anywhere in the
    call stack without explicit passing.
    """

    request_id: str
    org_id: uuid.UUID
    user_id: uuid.UUID | None
    agent_id: uuid.UUID | None
    auth_method: str  # "jwt" or "api_key"

    def __repr__(self) -> str:
        return (
            f"RequestContext(request_id={self.request_id}, "
            f"org_id={self.org_id}, user_id={self.user_id}, "
            f"agent_id={self.agent_id}, auth_method={self.auth_method})"
        )


def get_current_context() -> RequestContext | None:
    """
    Get the current request context from contextvars.

    Returns:
        RequestContext if set, None otherwise
    """
    return _request_context_var.get()


def set_current_context(context: RequestContext) -> None:
    """
    Set the current request context in contextvars.

    Args:
        context: RequestContext to set
    """
    _request_context_var.set(context)


def clear_current_context() -> None:
    """Clear any previously stored request context."""
    _request_context_var.set(None)


async def _try_jwt_auth(
    credentials: HTTPAuthorizationCredentials | None,
    db: AsyncSession,
) -> RequestContext | None:
    """
    Try to authenticate using JWT token.

    Args:
        credentials: HTTP Bearer credentials
        db: Database session

    Returns:
        RequestContext if JWT is valid, None otherwise
    """
    if not credentials:
        return None

    try:
        token = credentials.credentials

        # Decode token
        payload = decode_token(token)

        # Verify token type
        token_type = payload.get("type")
        if token_type != "access":
            logger.debug("Invalid token type", token_type=token_type)
            return None

        # Extract user ID
        user_id_str: str | None = payload.get("sub")
        if not user_id_str:
            logger.debug("Missing user ID in token")
            return None

        user_id = uuid.UUID(user_id_str)

        # Fetch user from database
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            logger.warning("User not found", user_id=user_id_str)
            return None

        if not user.is_active:
            logger.warning("Inactive user", user_id=user_id_str)
            return None

        # Extract agent_id from token if present
        agent_id_str = payload.get("agent_id")
        agent_id = uuid.UUID(agent_id_str) if agent_id_str else None

        logger.debug(
            "JWT authentication successful",
            user_id=str(user.id),
            org_id=str(user.org_id),
        )

        return RequestContext(
            request_id="",  # Will be set by caller
            org_id=user.org_id,
            user_id=user.id,
            agent_id=agent_id,
            auth_method="jwt",
        )

    except HTTPException:
        # Token decode failed - this is expected for invalid tokens
        return None
    except Exception as e:
        logger.warning("JWT authentication error", error=str(e))
        return None


async def _try_api_key_auth(
    x_api_key: str | None,
    db: AsyncSession,
    redis: Redis,
) -> RequestContext | None:
    """
    Try to authenticate using API key.

    Args:
        x_api_key: API key from header
        db: Database session
        redis: Redis client

    Returns:
        RequestContext if API key is valid, None otherwise
    """
    if not x_api_key:
        return None

    try:
        # Look up API key
        context = await lookup_api_key(db, redis, x_api_key)

        if not context:
            return None

        logger.debug(
            "API key authentication successful",
            org_id=str(context["org_id"]),
            key_id=str(context["key_id"]),
        )

        return RequestContext(
            request_id="",  # Will be set by caller
            org_id=context["org_id"],
            user_id=context["user_id"],
            agent_id=context["agent_id"],
            auth_method="api_key",
        )

    except Exception as e:
        logger.warning("API key authentication error", error=str(e))
        return None


async def get_request_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)] = None,
    x_api_key: Annotated[str | None, Header()] = None,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    redis: Annotated[Redis, Depends(get_redis)] = None,
) -> RequestContext | None:
    """
    FastAPI dependency that extracts authentication context from request.

    Tries JWT first, then falls back to API key. Returns None if neither
    authentication method succeeds.

    The context is also stored in contextvars for access anywhere in the
    call stack.

    Args:
        credentials: Optional JWT Bearer credentials
        x_api_key: Optional API key from header
        db: Database session
        redis: Redis client

    Returns:
        RequestContext if authenticated, None otherwise
    """
    # Try JWT first
    context = await _try_jwt_auth(credentials, db)

    # Fall back to API key
    if not context:
        context = await _try_api_key_auth(x_api_key, db, redis)

    # Store in contextvars if found
    if context:
        # Generate request ID if not already set
        if not context.request_id:
            context.request_id = str(uuid.uuid4())

        set_current_context(context)
        request.state.request_context = context

        logger.debug(
            "Request context established",
            auth_method=context.auth_method,
            org_id=str(context.org_id),
        )

    return context


async def require_auth(
    context: Annotated[RequestContext | None, Depends(get_request_context)] = None,
) -> RequestContext:
    """
    FastAPI dependency that requires authentication.

    Wraps get_request_context and raises 401 if no valid authentication found.

    Args:
        context: Request context from get_request_context

    Returns:
        RequestContext

    Raises:
        HTTPException: 401 if not authenticated
    """
    if not context:
        logger.warning("Authentication required but not provided")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return context
