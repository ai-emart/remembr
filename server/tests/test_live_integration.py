"""Docker-backed integration tests for the most important live flows."""

from __future__ import annotations

import json
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.api_keys import hash_api_key
from app.services.cache import make_key


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


async def _register_and_login(live_client, org_name: str) -> tuple[str, str]:
    response = await live_client.post(
        "/api/v1/auth/register",
        json={
            "email": _unique_email("live"),
            "password": "password123",
            "org_name": org_name,
        },
    )
    assert response.status_code == 201
    payload = response.json()["data"]
    return payload["access_token"], payload["refresh_token"]


@dataclass
class _CapturedWebhookRequest:
    path: str
    body: bytes
    headers: dict[str, str]


@contextmanager
def _webhook_receiver():
    captured: list[_CapturedWebhookRequest] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            captured.append(
                _CapturedWebhookRequest(
                    path=self.path,
                    body=body,
                    headers={key: value for key, value in self.headers.items()},
                )
            )
            self.send_response(204)
            self.end_headers()

        def log_message(self, format, *args):  # noqa: A003
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/webhook", captured
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.live_integration
async def test_live_auth_api_key_and_short_term_memory_flow(live_client, real_redis):
    access_token, _ = await _register_and_login(live_client, org_name="Live Redis Org")

    health_response = await live_client.get("/api/v1/health")
    assert health_response.status_code == 200
    assert health_response.json()["data"]["redis_status"] == "healthy"

    api_key_response = await live_client.post(
        "/api/v1/api-keys",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"name": "live-test-key"},
    )
    assert api_key_response.status_code == 201
    api_key_payload = api_key_response.json()["data"]
    raw_api_key = api_key_payload["api_key"]

    me_response = await live_client.get(
        "/api/v1/me",
        headers={"X-API-Key": raw_api_key},
    )
    assert me_response.status_code == 200
    me_payload = me_response.json()["data"]
    assert me_payload["auth_method"] == "api_key"

    cache_key = f"api_key:{hash_api_key(raw_api_key)}"
    cached_auth = await real_redis.get(cache_key)
    assert cached_auth is not None
    assert me_payload["org_id"] in cached_auth

    session_response = await live_client.post(
        "/api/v1/sessions",
        headers={"X-API-Key": raw_api_key},
        json={"metadata": {"source": "live-integration"}},
    )
    assert session_response.status_code == 201
    session_id = session_response.json()["data"]["session_id"]

    memory_response = await live_client.post(
        "/api/v1/memory",
        headers={"X-API-Key": raw_api_key},
        json={
            "role": "user",
            "content": "Live Redis integration message",
            "session_id": session_id,
            "tags": ["live", "redis"],
        },
    )
    assert memory_response.status_code == 201
    memory_payload = memory_response.json()["data"]
    assert memory_payload["session_id"] == session_id

    short_term_key = make_key("short_term", session_id, "window")
    stored_window = await real_redis.get(short_term_key)
    assert stored_window is not None
    assert "Live Redis integration message" in stored_window

    session_detail_response = await live_client.get(
        f"/api/v1/sessions/{session_id}",
        headers={"X-API-Key": raw_api_key},
    )
    assert session_detail_response.status_code == 200
    session_detail = session_detail_response.json()["data"]
    assert session_detail["messages"][0]["content"] == "Live Redis integration message"
    assert session_detail["token_usage"]["used"] > 0


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.live_integration
async def test_live_webhook_delivery_over_real_http(live_client, db, monkeypatch):
    from app.tasks.webhooks import _deliver_webhook_once, deliver_webhook

    access_token, _ = await _register_and_login(live_client, org_name="Live Webhook Org")

    with _webhook_receiver() as (webhook_url, captured):
        monkeypatch.setattr(deliver_webhook, "delay", lambda delivery_id: None)

        create_response = await live_client.post(
            "/api/v1/webhooks",
            headers={"Authorization": f"Bearer {access_token}"},
            json={
                "url": webhook_url,
                "events": ["memory.stored"],
                "active": True,
            },
        )
        assert create_response.status_code == 201
        webhook_id = create_response.json()["data"]["id"]

        test_response = await live_client.post(
            f"/api/v1/webhooks/{webhook_id}/test",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert test_response.status_code == 200
        delivery_id = test_response.json()["data"]["delivery_id"]

        session_factory = async_sessionmaker(
            db.bind,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        await _deliver_webhook_once(delivery_id, session_factory=session_factory)

        assert len(captured) == 1
        delivered = captured[0]
        delivered_payload = json.loads(delivered.body.decode("utf-8"))
        assert delivered.path == "/webhook"
        assert delivered.headers["X-Remembr-Delivery"] == delivery_id
        assert delivered.headers["X-Remembr-Event"] == "webhook.test"
        assert delivered.headers["X-Remembr-Signature"].startswith("sha256=")
        assert delivered_payload["event"] == "webhook.test"

        deliveries_response = await live_client.get(
            f"/api/v1/webhooks/{webhook_id}/deliveries",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        assert deliveries_response.status_code == 200
        deliveries = deliveries_response.json()["data"]
        assert deliveries[0]["id"] == delivery_id
        assert deliveries[0]["status"] == "delivered"
        assert deliveries[0]["response_status_code"] == 204
