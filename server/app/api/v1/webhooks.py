"""Webhook registration and delivery endpoints."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from pydantic import AnyHttpUrl, BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.responses import StandardResponse, success
from app.db.session import get_db
from app.exceptions import NotFoundError, ValidationError
from app.middleware.context import RequestContext, require_auth
from app.models import Webhook, WebhookDelivery
from app.services.events import SUPPORTED_EVENTS
from app.services.scoping import ScopeResolver

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _generate_secret() -> str:
    return secrets.token_hex(32)


def _validate_events(events: list[str]) -> list[str]:
    invalid = sorted(set(events).difference(SUPPORTED_EVENTS))
    if invalid:
        raise ValidationError(
            "Unsupported webhook event",
            details={"invalid_events": invalid, "supported_events": sorted(SUPPORTED_EVENTS)},
        )
    return events


async def _get_scoped_webhook(db: AsyncSession, scope, webhook_id: UUID) -> Webhook:
    query = (
        select(Webhook)
        .where(Webhook.id == webhook_id)
        .where(Webhook.org_id == UUID(scope.org_id))
        .where(Webhook.not_deleted())
    )
    result = await db.execute(query)
    webhook = result.scalar_one_or_none()
    if webhook is None:
        raise NotFoundError("Webhook not found")
    return webhook


class WebhookCreateRequest(BaseModel):
    url: AnyHttpUrl
    events: list[str] = Field(min_length=1)
    active: bool = True

    @model_validator(mode="after")
    def _validate_supported_events(self) -> WebhookCreateRequest:
        self.events = _validate_events(self.events)
        return self


class WebhookUpdateRequest(BaseModel):
    url: AnyHttpUrl | None = None
    events: list[str] | None = None
    active: bool | None = None

    @model_validator(mode="after")
    def _validate_supported_events(self) -> WebhookUpdateRequest:
        if self.events is not None:
            self.events = _validate_events(self.events)
        return self


class WebhookResponse(BaseModel):
    id: str
    org_id: str
    url: str
    events: list[str]
    active: bool
    created_at: datetime
    updated_at: datetime
    last_delivery_at: datetime | None
    last_delivery_status: str | None
    failure_count: int


class WebhookSecretResponse(WebhookResponse):
    secret: str


class WebhookDeliveryResponse(BaseModel):
    id: str
    webhook_id: str
    event: str
    payload: dict[str, Any]
    status: str
    attempts: int
    last_attempt_at: datetime | None
    response_status_code: int | None
    response_body_snippet: str | None
    created_at: datetime


class WebhookDeleteResponse(BaseModel):
    deleted: bool
    webhook_id: str


def _to_webhook_response(webhook: Webhook) -> WebhookResponse:
    return WebhookResponse(
        id=str(webhook.id),
        org_id=str(webhook.org_id),
        url=webhook.url,
        events=webhook.events,
        active=webhook.active,
        created_at=webhook.created_at,
        updated_at=webhook.updated_at,
        last_delivery_at=webhook.last_delivery_at,
        last_delivery_status=webhook.last_delivery_status,
        failure_count=webhook.failure_count,
    )


def _to_secret_response(webhook: Webhook, secret: str) -> WebhookSecretResponse:
    return WebhookSecretResponse(**_to_webhook_response(webhook).model_dump(), secret=secret)


@router.post(
    "",
    response_model=StandardResponse[WebhookSecretResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook(
    payload: WebhookCreateRequest,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StandardResponse[WebhookSecretResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    secret = _generate_secret()
    webhook = Webhook(
        org_id=UUID(scope.org_id),
        url=str(payload.url),
        events=payload.events,
        secret=secret,
        active=payload.active,
    )
    db.add(webhook)
    await db.flush()
    await db.refresh(webhook)
    await db.commit()
    return success(_to_secret_response(webhook, secret), request_id=ctx.request_id)


@router.get("", response_model=StandardResponse[list[WebhookResponse]])
async def list_webhooks(
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StandardResponse[list[WebhookResponse]]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    result = await db.execute(
        select(Webhook)
        .where(Webhook.org_id == UUID(scope.org_id))
        .where(Webhook.not_deleted())
        .order_by(Webhook.created_at.desc())
    )
    return success(
        [_to_webhook_response(webhook) for webhook in result.scalars().all()],
        request_id=ctx.request_id,
    )


@router.get("/{webhook_id}", response_model=StandardResponse[WebhookResponse])
async def get_webhook(
    webhook_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StandardResponse[WebhookResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    webhook = await _get_scoped_webhook(db, scope, webhook_id)
    return success(_to_webhook_response(webhook), request_id=ctx.request_id)


@router.patch("/{webhook_id}", response_model=StandardResponse[WebhookResponse])
async def update_webhook(
    webhook_id: UUID,
    payload: WebhookUpdateRequest,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StandardResponse[WebhookResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    webhook = await _get_scoped_webhook(db, scope, webhook_id)
    if payload.url is not None:
        webhook.url = str(payload.url)
    if payload.events is not None:
        webhook.events = payload.events
    if payload.active is not None:
        webhook.active = payload.active
    await db.commit()
    await db.refresh(webhook)
    return success(_to_webhook_response(webhook), request_id=ctx.request_id)


@router.delete("/{webhook_id}", response_model=StandardResponse[WebhookDeleteResponse])
async def delete_webhook(
    webhook_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StandardResponse[WebhookDeleteResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    webhook = await _get_scoped_webhook(db, scope, webhook_id)
    webhook.deleted_at = datetime.now(UTC)
    webhook.active = False
    await db.commit()
    return success(
        WebhookDeleteResponse(deleted=True, webhook_id=str(webhook_id)),
        request_id=ctx.request_id,
    )


@router.post("/{webhook_id}/rotate-secret", response_model=StandardResponse[WebhookSecretResponse])
async def rotate_webhook_secret(
    webhook_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StandardResponse[WebhookSecretResponse]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    webhook = await _get_scoped_webhook(db, scope, webhook_id)
    secret = _generate_secret()
    webhook.secret = secret
    webhook.failure_count = 0
    await db.commit()
    await db.refresh(webhook)
    return success(_to_secret_response(webhook, secret), request_id=ctx.request_id)


@router.get(
    "/{webhook_id}/deliveries",
    response_model=StandardResponse[list[WebhookDeliveryResponse]],
)
async def list_webhook_deliveries(
    webhook_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(20, ge=1, le=100),
) -> StandardResponse[list[WebhookDeliveryResponse]]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    webhook = await _get_scoped_webhook(db, scope, webhook_id)
    result = await db.execute(
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == webhook.id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(limit)
    )
    return success(
        [
            WebhookDeliveryResponse(
                id=str(delivery.id),
                webhook_id=str(delivery.webhook_id),
                event=delivery.event,
                payload=delivery.payload,
                status=delivery.status,
                attempts=delivery.attempts,
                last_attempt_at=delivery.last_attempt_at,
                response_status_code=delivery.response_status_code,
                response_body_snippet=delivery.response_body_snippet,
                created_at=delivery.created_at,
            )
            for delivery in result.scalars().all()
        ],
        request_id=ctx.request_id,
    )


@router.post("/{webhook_id}/test", response_model=StandardResponse[dict[str, Any]])
async def test_webhook(
    webhook_id: UUID,
    ctx: Annotated[RequestContext, Depends(require_auth)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StandardResponse[dict[str, Any]]:
    scope = ScopeResolver.resolve_writable_scope(ScopeResolver.from_request_context(ctx))
    webhook = await _get_scoped_webhook(db, scope, webhook_id)
    payload = {
        "event": "webhook.test",
        "webhook_id": str(webhook.id),
        "org_id": str(webhook.org_id),
        "request_id": ctx.request_id,
        "sent_at": datetime.now(UTC).isoformat(),
    }
    delivery = WebhookDelivery(
        webhook_id=webhook.id,
        event="webhook.test",
        payload=payload,
        status="pending",
    )
    db.add(delivery)
    await db.flush()
    delivery_id = str(delivery.id)
    await db.commit()

    from app.tasks.webhooks import deliver_webhook

    deliver_webhook.delay(delivery_id)
    return success({"delivery_id": delivery_id, "event": "webhook.test"}, request_id=ctx.request_id)
