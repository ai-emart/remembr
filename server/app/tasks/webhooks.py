"""Celery tasks for webhook delivery."""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import hmac
import json
from datetime import UTC, datetime

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.celery_app import celery_app
from app.db.session import AsyncSessionLocal


class WebhookDeliveryError(Exception):
    """Raised when a webhook delivery should be retried."""


def _run_async(coro):
    """Run a coroutine in a dedicated thread with its own event loop."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(asyncio.run, coro).result()


def build_webhook_signature(secret: str, raw_body: bytes) -> str:
    """Compute the signed HMAC header value for a webhook body."""
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


async def _deliver_webhook_once(
    delivery_id: str,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Attempt a single webhook delivery and raise on retryable failure."""
    from app.models import Webhook, WebhookDelivery

    factory = session_factory or AsyncSessionLocal
    async with factory() as db:
        delivery = await db.get(WebhookDelivery, delivery_id)
        if delivery is None:
            logger.warning("Skipping webhook delivery: row not found", delivery_id=delivery_id)
            return

        webhook = await db.get(Webhook, delivery.webhook_id)
        if webhook is None or webhook.deleted_at is not None or not webhook.active:
            delivery.status = "failed"
            delivery.response_body_snippet = "Webhook missing or inactive."
            await db.commit()
            return

        delivery.attempts += 1
        delivery.last_attempt_at = datetime.now(UTC)
        raw_body = json.dumps(
            delivery.payload,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Remembr-Event": delivery.event,
            "X-Remembr-Delivery": str(delivery.id),
            "X-Remembr-Signature": build_webhook_signature(webhook.secret, raw_body),
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(webhook.url, content=raw_body, headers=headers)
        except httpx.TimeoutException as exc:
            delivery.response_status_code = None
            delivery.response_body_snippet = "timeout"
            await db.commit()
            raise WebhookDeliveryError("Webhook delivery timed out") from exc
        except httpx.HTTPError as exc:
            delivery.response_status_code = None
            delivery.response_body_snippet = repr(exc)[:500]
            await db.commit()
            raise WebhookDeliveryError("Webhook delivery failed") from exc

        delivery.response_status_code = response.status_code
        delivery.response_body_snippet = response.text[:500]

        if 200 <= response.status_code < 300:
            delivery.status = "delivered"
            webhook.last_delivery_at = datetime.now(UTC)
            webhook.last_delivery_status = "delivered"
            webhook.failure_count = 0
            await db.commit()
            return

        webhook.last_delivery_at = datetime.now(UTC)
        webhook.last_delivery_status = f"http_{response.status_code}"
        await db.commit()
        raise WebhookDeliveryError(f"Webhook returned status {response.status_code}")


async def _mark_delivery_failed(
    delivery_id: str,
    reason: str,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> None:
    """Persist final failure state for a delivery and update the parent webhook."""
    from app.models import Webhook, WebhookDelivery

    factory = session_factory or AsyncSessionLocal
    async with factory() as db:
        delivery = await db.get(WebhookDelivery, delivery_id)
        if delivery is None:
            return

        webhook = await db.get(Webhook, delivery.webhook_id)
        delivery.status = "failed"
        delivery.response_body_snippet = reason[:500]

        if webhook is not None:
            webhook.failure_count += 1
            webhook.last_delivery_at = datetime.now(UTC)
            webhook.last_delivery_status = "failed"
            if webhook.failure_count >= 20:
                webhook.active = False

        await db.commit()


@celery_app.task(
    bind=True,
    name="app.tasks.webhooks.deliver_webhook",
    autoretry_for=(WebhookDeliveryError,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=5,
)
def deliver_webhook(self, delivery_id: str) -> None:
    """Deliver a queued webhook event."""
    try:
        _run_async(_deliver_webhook_once(delivery_id))
    except WebhookDeliveryError as exc:
        if self.request.retries >= self.max_retries:
            _run_async(_mark_delivery_failed(delivery_id, str(exc)))
            logger.error(
                "Webhook delivery permanently failed",
                delivery_id=delivery_id,
                error=str(exc),
            )
            return
        raise
