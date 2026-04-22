import sys
import uuid
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.responses import error
from app.api.v1.router import router as v1_router
from app.config import get_settings
from app.error_codes import INTERNAL_ERROR, VALIDATION_ERROR
from app.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    RemembrException,
    ValidationError,
)
from app.middleware.rate_limit import setup_rate_limiting
from app.services.search_config import WEIGHT_SUM_ERROR_MESSAGE


def configure_logging() -> None:
    """Configure structured JSON logging with loguru."""
    settings = get_settings()

    # Remove default handler
    logger.remove()

    # Add JSON structured logging
    logger.add(
        sys.stdout,
        level=settings.log_level,
        serialize=True,
    )


def configure_sentry() -> None:
    """Initialize Sentry if DSN is configured."""
    settings = get_settings()

    if settings.sentry_dsn:
        sentry_sdk.init(
            dsn=settings.sentry_dsn.get_secret_value(),
            environment=settings.environment,
            traces_sample_rate=1.0 if settings.environment == "local" else 0.1,
        )
        logger.info("Sentry initialized", environment=settings.environment)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    configure_logging()
    configure_sentry()

    # Initialize Redis
    from app.db.redis import init_redis
    from app.observability import setup_otel, shutdown_otel

    try:
        await init_redis()
        from app.celery_app import celery_app
        from app.db.redis import get_redis_client
        from app.db.session import engine

        setup_otel(
            app,
            engine=engine,
            redis_client=get_redis_client(),
            celery_app=celery_app,
        )
        logger.info("Application startup", version="0.1.0", redis="connected")
    except Exception as e:
        logger.error("Failed to initialize Redis", error=str(e))
        # Continue without Redis - endpoints will handle gracefully
        logger.warning("Application starting without Redis")

    yield

    # Shutdown
    from app.db.redis import close_redis

    await shutdown_otel()
    await close_redis()
    logger.info("Application shutdown")


def create_app() -> FastAPI:
    """
    Application factory for creating configured FastAPI instances.

    Returns:
        Configured FastAPI application
    """
    settings = get_settings()

    app = FastAPI(
        title="Remembr API",
        description="Persistent memory infrastructure for AI agents",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=(
            settings.cors_origins if settings.cors_origins else (["*"] if settings.is_local else [])
        ),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request context middleware
    @app.middleware("http")
    async def add_request_context(request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id

        # Import here to avoid circular dependency
        from app.middleware.context import get_current_context

        # Start with request_id in logger context
        log_context = {"request_id": request_id}

        with logger.contextualize(**log_context):
            logger.info(
                "Request started",
                method=request.method,
                path=request.url.path,
            )

            # Process request
            response = await call_next(request)

            # After request processing, check if we have auth context
            ctx = get_current_context()
            if ctx:
                # Update logger context with auth info
                log_context.update(
                    {
                        "org_id": str(ctx.org_id),
                        "user_id": str(ctx.user_id) if ctx.user_id else None,
                        "agent_id": str(ctx.agent_id) if ctx.agent_id else None,
                        "auth_method": ctx.auth_method,
                    }
                )

                # Add to response headers
                response.headers["X-Org-ID"] = str(ctx.org_id)

            response.headers["X-Request-ID"] = request_id

            # Log completion with full context
            with logger.contextualize(**log_context):
                logger.info(
                    "Request completed",
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                )

            return response

    # Global exception handlers
    @app.exception_handler(RemembrException)
    async def remembr_exception_handler(request: Request, exc: RemembrException):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.warning(
            "Application exception",
            request_id=request_id,
            code=exc.code,
            status_code=exc.status_code,
            message=exc.message,
        )
        return error(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            request_id=request_id,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        request_id = getattr(request.state, "request_id", "unknown")
        # Pydantic v2 may embed non-serializable objects in the error ctx (e.g. the
        # original ValueError instance).  Strip ctx before JSON serialization.
        sanitized = [
            {k: v for k, v in e.items() if k not in ("ctx", "url")}
            for e in exc.errors()
        ]
        status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
        if any(WEIGHT_SUM_ERROR_MESSAGE in str(item.get("msg", "")) for item in sanitized):
            status_code = status.HTTP_400_BAD_REQUEST
        logger.warning("Validation error", request_id=request_id, errors=sanitized)
        return error(
            code=VALIDATION_ERROR,
            message="Request validation failed",
            status_code=status_code,
            request_id=request_id,
            details={"errors": sanitized},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.warning(
            "HTTP exception", request_id=request_id, status_code=exc.status_code, detail=exc.detail
        )
        mapped: RemembrException
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            mapped = AuthenticationError(str(exc.detail))
        elif exc.status_code == status.HTTP_403_FORBIDDEN:
            mapped = AuthorizationError(str(exc.detail))
        elif exc.status_code == status.HTTP_404_NOT_FOUND:
            mapped = NotFoundError(str(exc.detail))
        elif exc.status_code == status.HTTP_409_CONFLICT:
            mapped = ConflictError(str(exc.detail))
        elif exc.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
            mapped = ValidationError(str(exc.detail))
        elif exc.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
            mapped = RateLimitError(str(exc.detail))
        else:
            mapped = RemembrException(str(exc.detail))
            mapped.status_code = exc.status_code
            mapped.code = f"HTTP_{exc.status_code}"

        return error(
            code=mapped.code,
            message=mapped.message,
            status_code=mapped.status_code,
            request_id=request_id,
            details=mapped.details,
        )

    from sqlalchemy.exc import IntegrityError

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.warning("Integrity error", request_id=request_id, error=str(exc))
        mapped = ConflictError("Resource conflict")
        return error(
            code=mapped.code,
            message=mapped.message,
            status_code=mapped.status_code,
            request_id=request_id,
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", "unknown")
        logger.exception("Unhandled exception", request_id=request_id)
        return error(
            code=INTERNAL_ERROR,
            message="An unexpected error occurred",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            request_id=request_id,
        )

    # Idempotency middleware — runs after auth context so org/user info is available
    from app.middleware.idempotency import idempotency_middleware

    app.middleware("http")(idempotency_middleware)

    # Enable API rate limiting
    setup_rate_limiting(app)

    # Mount versioned API router
    app.include_router(v1_router, prefix=settings.api_v1_prefix)

    # Admin UI — dev/staging only, never production
    if not settings.is_production:
        from pathlib import Path

        from fastapi.staticfiles import StaticFiles

        from app.admin.router import router as admin_router

        _static_dir = Path(__file__).parent / "admin" / "static"
        app.mount("/admin/static", StaticFiles(directory=str(_static_dir)), name="admin-static")
        app.include_router(admin_router)
    else:
        logger.warning("Admin UI disabled in production environment")

    return app


# Create app instance
app = create_app()
