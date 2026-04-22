from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import Organization, User, Webhook, WebhookDelivery
from app.services.auth import create_access_token
from app.services.events import emit_event
from app.tasks.webhooks import (
    WebhookDeliveryError,
    _deliver_webhook_once,
    _mark_delivery_failed,
    build_webhook_signature,
    deliver_webhook,
)

pytestmark = pytest.mark.integration


def _session_factory(db: AsyncSession) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)


async def _auth_headers(db: AsyncSession) -> dict[str, str]:
    org = Organization(name=f"Webhook Org {uuid.uuid4().hex[:8]}")
    db.add(org)
    await db.flush()
    user = User(
        org_id=org.id,
        email=f"webhook-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="hashed",
        is_active=True,
    )
    db.add(user)
    await db.commit()
    token = create_access_token({"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


@dataclass
class _CapturedRequest:
    url: str
    content: bytes
    headers: dict[str, str]


class _FakeAsyncClient:
    captured: list[_CapturedRequest] = []
    response_status = 204
    response_body = "ok"

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    async def post(self, url: str, *, content: bytes, headers: dict[str, str]) -> httpx.Response:
        self.captured.append(_CapturedRequest(url=url, content=content, headers=headers))
        request = httpx.Request("POST", url, content=content, headers=headers)
        return httpx.Response(self.response_status, text=self.response_body, request=request)


@pytest.mark.asyncio
async def test_webhook_register_list_update_delete_round_trip(client, db: AsyncSession):
    headers = await _auth_headers(db)

    create_resp = await client.post(
        "/api/v1/webhooks",
        headers=headers,
        json={
            "url": "https://example.com/webhooks",
            "events": ["memory.stored", "session.created"],
            "active": True,
        },
    )
    assert create_resp.status_code == 201
    created = create_resp.json()["data"]
    assert created["secret"]
    assert created["events"] == ["memory.stored", "session.created"]

    list_resp = await client.get("/api/v1/webhooks", headers=headers)
    assert list_resp.status_code == 200
    listed = list_resp.json()["data"]
    assert len(listed) == 1
    assert "secret" not in listed[0]

    get_resp = await client.get(f"/api/v1/webhooks/{created['id']}", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["url"] == "https://example.com/webhooks"

    update_resp = await client.patch(
        f"/api/v1/webhooks/{created['id']}",
        headers=headers,
        json={"active": False, "events": ["memory.deleted"]},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["data"]["active"] is False
    assert update_resp.json()["data"]["events"] == ["memory.deleted"]

    delete_resp = await client.delete(f"/api/v1/webhooks/{created['id']}", headers=headers)
    assert delete_resp.status_code == 200
    assert delete_resp.json()["data"]["deleted"] is True

    missing_resp = await client.get(f"/api/v1/webhooks/{created['id']}", headers=headers)
    assert missing_resp.status_code == 404


@pytest.mark.asyncio
async def test_webhook_test_event_creates_delivery_and_lists_it(client, db: AsyncSession):
    headers = await _auth_headers(db)

    create_resp = await client.post(
        "/api/v1/webhooks",
        headers=headers,
        json={"url": "https://example.com/test-webhook", "events": ["memory.stored"]},
    )
    webhook_id = create_resp.json()["data"]["id"]

    test_resp = await client.post(f"/api/v1/webhooks/{webhook_id}/test", headers=headers)
    assert test_resp.status_code == 200
    delivery_id = test_resp.json()["data"]["delivery_id"]

    deliveries_resp = await client.get(
        f"/api/v1/webhooks/{webhook_id}/deliveries",
        headers=headers,
    )
    assert deliveries_resp.status_code == 200
    deliveries = deliveries_resp.json()["data"]
    assert len(deliveries) == 1
    assert deliveries[0]["id"] == delivery_id
    assert deliveries[0]["event"] == "webhook.test"
    assert deliveries[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_event_creates_pending_delivery_and_sends_signed_post(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    org = Organization(name="Delivery Org")
    db.add(org)
    await db.flush()
    webhook = Webhook(
        org_id=org.id,
        url="https://receiver.example/webhook",
        events=["memory.stored"],
        secret="super-secret",
        active=True,
    )
    db.add(webhook)
    await db.commit()

    queued: list[str] = []
    monkeypatch.setattr("app.tasks.webhooks.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(deliver_webhook, "delay", lambda delivery_id: queued.append(delivery_id))

    delivery_ids = await emit_event(
        event_name="memory.stored",
        payload={"episode_id": "ep_1", "kind": "test"},
        org_id=org.id,
        session_factory=_session_factory(db),
    )

    assert delivery_ids == queued
    delivery = await db.get(WebhookDelivery, uuid.UUID(delivery_ids[0]))
    assert delivery is not None
    assert delivery.status == "pending"

    await _deliver_webhook_once(delivery_ids[0], session_factory=_session_factory(db))
    await db.refresh(delivery)
    await db.refresh(webhook)

    assert delivery.status == "delivered"
    assert webhook.failure_count == 0
    assert len(_FakeAsyncClient.captured) == 1

    captured = _FakeAsyncClient.captured[-1]
    assert captured.headers["X-Remembr-Event"] == "memory.stored"
    assert captured.headers["X-Remembr-Delivery"] == delivery_ids[0]
    assert captured.headers["X-Remembr-Signature"] == build_webhook_signature(
        webhook.secret,
        captured.content,
    )
    assert json.loads(captured.content.decode("utf-8")) == {"episode_id": "ep_1", "kind": "test"}


@pytest.mark.asyncio
async def test_signature_verification_matches_receiver_computation(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    org = Organization(name="Signature Org")
    db.add(org)
    await db.flush()
    webhook = Webhook(
        org_id=org.id,
        url="https://receiver.example/signed",
        events=["session.created"],
        secret="rotate-me",
        active=True,
    )
    db.add(webhook)
    await db.flush()
    delivery = WebhookDelivery(
        webhook_id=webhook.id,
        event="session.created",
        payload={"session_id": "sess_1"},
        status="pending",
    )
    db.add(delivery)
    await db.commit()

    _FakeAsyncClient.captured.clear()
    monkeypatch.setattr("app.tasks.webhooks.httpx.AsyncClient", _FakeAsyncClient)

    await _deliver_webhook_once(str(delivery.id), session_factory=_session_factory(db))

    captured = _FakeAsyncClient.captured[-1]
    receiver_sig = build_webhook_signature(webhook.secret, captured.content)
    assert receiver_sig == captured.headers["X-Remembr-Signature"]


@pytest.mark.asyncio
async def test_non_2xx_response_records_retryable_failure(
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    org = Organization(name="Failure Org")
    db.add(org)
    await db.flush()
    webhook = Webhook(
        org_id=org.id,
        url="https://receiver.example/fail",
        events=["memory.deleted"],
        secret="bad-news",
        active=True,
    )
    db.add(webhook)
    await db.flush()
    delivery = WebhookDelivery(
        webhook_id=webhook.id,
        event="memory.deleted",
        payload={"episode_id": "ep_bad"},
        status="pending",
    )
    db.add(delivery)
    await db.commit()

    _FakeAsyncClient.response_status = 500
    _FakeAsyncClient.response_body = "server exploded"
    monkeypatch.setattr("app.tasks.webhooks.httpx.AsyncClient", _FakeAsyncClient)

    with pytest.raises(WebhookDeliveryError):
        await _deliver_webhook_once(str(delivery.id), session_factory=_session_factory(db))

    await db.refresh(delivery)
    assert delivery.attempts == 1
    assert delivery.response_status_code == 500
    assert delivery.status == "pending"
    assert deliver_webhook.max_retries == 5


@pytest.mark.asyncio
async def test_inactive_webhook_is_skipped(db: AsyncSession, monkeypatch: pytest.MonkeyPatch):
    org = Organization(name="Inactive Org")
    db.add(org)
    await db.flush()
    webhook = Webhook(
        org_id=org.id,
        url="https://receiver.example/skip",
        events=["memory.stored"],
        secret="skip-me",
        active=False,
    )
    db.add(webhook)
    await db.commit()

    queued: list[str] = []
    monkeypatch.setattr(deliver_webhook, "delay", lambda delivery_id: queued.append(delivery_id))

    delivery_ids = await emit_event(
        event_name="memory.stored",
        payload={"episode_id": "ep_2"},
        org_id=org.id,
        session_factory=_session_factory(db),
    )

    assert delivery_ids == []
    assert queued == []


@pytest.mark.asyncio
async def test_twenty_consecutive_failures_auto_deactivate(db: AsyncSession):
    org = Organization(name="Auto Deactivate Org")
    db.add(org)
    await db.flush()
    webhook = Webhook(
        org_id=org.id,
        url="https://receiver.example/deactivate",
        events=["memory.deleted"],
        secret="fail-count",
        active=True,
        failure_count=19,
    )
    db.add(webhook)
    await db.flush()
    delivery = WebhookDelivery(
        webhook_id=webhook.id,
        event="memory.deleted",
        payload={"episode_id": "ep_20"},
        status="pending",
    )
    db.add(delivery)
    await db.commit()

    await _mark_delivery_failed(
        str(delivery.id),
        "max retries reached",
        session_factory=_session_factory(db),
    )
    await db.refresh(webhook)
    await db.refresh(delivery)

    assert webhook.failure_count == 20
    assert webhook.active is False
    assert delivery.status == "failed"


@pytest.mark.asyncio
async def test_rotating_secret_invalidates_old_one(
    client,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
):
    headers = await _auth_headers(db)
    create_resp = await client.post(
        "/api/v1/webhooks",
        headers=headers,
        json={"url": "https://example.com/rotate", "events": ["session.created"]},
    )
    secret_before = create_resp.json()["data"]["secret"]
    webhook_id = create_resp.json()["data"]["id"]

    rotate_resp = await client.post(f"/api/v1/webhooks/{webhook_id}/rotate-secret", headers=headers)
    secret_after = rotate_resp.json()["data"]["secret"]
    assert secret_before != secret_after

    delivery = WebhookDelivery(
        webhook_id=uuid.UUID(webhook_id),
        event="session.created",
        payload={"session_id": "sess_rotated"},
        status="pending",
    )
    db.add(delivery)
    await db.commit()

    _FakeAsyncClient.response_status = 204
    _FakeAsyncClient.response_body = "ok"
    _FakeAsyncClient.captured.clear()
    monkeypatch.setattr("app.tasks.webhooks.httpx.AsyncClient", _FakeAsyncClient)

    await _deliver_webhook_once(str(delivery.id), session_factory=_session_factory(db))

    captured = _FakeAsyncClient.captured[-1]
    assert captured.headers["X-Remembr-Signature"] == build_webhook_signature(
        secret_after,
        captured.content,
    )
    assert captured.headers["X-Remembr-Signature"] != build_webhook_signature(
        secret_before,
        captured.content,
    )
