"""Event emission for outbound webhooks."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import AsyncSessionLocal
from app.models import Webhook, WebhookDelivery

SUPPORTED_EVENTS = {
    "memory.stored",
    "embedding.ready",
    "session.created",
    "memory.deleted",
    "checkpoint.created",
}


async def emit_event(
    event_name: str,
    payload: dict[str, Any],
    org_id: UUID,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> list[str]:
    """Queue webhook deliveries for an event."""
    if event_name not in SUPPORTED_EVENTS:
        raise ValueError(f"Unsupported event: {event_name}")

    factory = session_factory or AsyncSessionLocal
    async with factory() as db:
        result = await db.execute(
            select(Webhook)
            .where(Webhook.org_id == org_id)
            .where(Webhook.active.is_(True))
            .where(Webhook.deleted_at.is_(None))
            .where(Webhook.events.any(event_name))
        )
        webhooks = list(result.scalars().all())

        if not webhooks:
            return []

        deliveries: list[WebhookDelivery] = []
        for webhook in webhooks:
            deliveries.append(
                WebhookDelivery(
                    webhook_id=webhook.id,
                    event=event_name,
                    payload=payload,
                    status="pending",
                )
            )

        db.add_all(deliveries)
        await db.commit()

        from app.tasks.webhooks import deliver_webhook

        for delivery in deliveries:
            deliver_webhook.delay(str(delivery.id))

        return [str(delivery.id) for delivery in deliveries]


async def emit_event_safely(
    event_name: str,
    payload: dict[str, Any],
    org_id: UUID,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> list[str]:
    """Best-effort event emission that never breaks the caller."""
    try:
        return await emit_event(
            event_name=event_name,
            payload=payload,
            org_id=org_id,
            session_factory=session_factory,
        )
    except Exception as exc:
        logger.error(
            "Failed to emit event",
            event_name=event_name,
            org_id=str(org_id),
            error=str(exc),
        )
        return []
