from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from remembr import RemembrClient


class MockRemembrAPI:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.sessions: dict[str, dict[str, Any]] = {}
        self.episodes: dict[str, dict[str, Any]] = {}
        self.checkpoints: dict[str, dict[str, Any]] = {}
        self.idempotency_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._session_counter = 0
        self._episode_counter = 0
        self._checkpoint_counter = 0

    def build_client(self) -> RemembrClient:
        client = RemembrClient(api_key="test-key", base_url="https://example.test/api/v1")
        client._client = httpx.AsyncClient(
            base_url=client.base_url,
            headers={
                "Authorization": f"Bearer {client.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(client.timeout),
            transport=httpx.MockTransport(self.handler),
        )
        return client

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        method = request.method.upper()
        path = request.url.path

        if method == "POST" and path == "/api/v1/sessions":
            return self._create_session(request)
        if method == "POST" and path == "/api/v1/memory":
            return self._store(request)
        if method == "POST" and path == "/api/v1/memory/search":
            return self._search(request)
        if method == "DELETE" and path.startswith("/api/v1/memory/session/"):
            return self._forget_session(request, path.rsplit("/", 1)[-1])
        if method == "DELETE" and path.startswith("/api/v1/memory/"):
            return self._forget_episode(request, path.rsplit("/", 1)[-1])
        if method == "GET" and path.startswith("/api/v1/sessions/") and path.endswith("/history"):
            session_id = path.split("/")[-2]
            return self._history(request, session_id)
        if method == "POST" and path.startswith("/api/v1/sessions/") and path.endswith("/checkpoint"):
            session_id = path.split("/")[-2]
            return self._checkpoint(request, session_id)
        if method == "POST" and path.startswith("/api/v1/sessions/") and path.endswith("/restore"):
            session_id = path.split("/")[-2]
            return self._restore(request, session_id)
        if method == "GET" and path.startswith("/api/v1/sessions/") and path.endswith("/checkpoints"):
            session_id = path.split("/")[-2]
            return self._list_checkpoints(request, session_id)

        return httpx.Response(
            404,
            request=request,
            json={"error": {"message": f"Unhandled mock route: {method} {path}"}},
        )

    def json_body(self, request: httpx.Request) -> dict[str, Any]:
        if not request.content:
            return {}
        return json.loads(request.content.decode("utf-8"))

    def payloads_for(self, method: str, path: str) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        for request in self.requests:
            if request.method.upper() == method.upper() and request.url.path == path:
                payloads.append(self.json_body(request))
        return payloads

    def headers_for(self, method: str, path: str) -> list[httpx.Headers]:
        return [
            request.headers
            for request in self.requests
            if request.method.upper() == method.upper() and request.url.path == path
        ]

    def _create_session(self, request: httpx.Request) -> httpx.Response:
        self._session_counter += 1
        session_id = f"sess-{self._session_counter}"
        payload = self.json_body(request)
        data = {
            "request_id": f"req-session-{self._session_counter}",
            "session_id": session_id,
            "org_id": "org-test",
            "created_at": self._now(),
            "metadata": payload.get("metadata") or {},
        }
        self.sessions[session_id] = data
        return self._response(request, data)

    def _store(self, request: httpx.Request) -> httpx.Response:
        payload = self.json_body(request)
        session_id = str(payload.get("session_id"))
        idempotency_key = request.headers.get("Idempotency-Key")
        cache_key = ("POST:/memory", idempotency_key or "")
        if idempotency_key and cache_key in self.idempotency_cache:
            return self._response(request, self.idempotency_cache[cache_key])

        self._episode_counter += 1
        episode_id = f"ep-{self._episode_counter}"
        data = {
            "request_id": f"req-store-{self._episode_counter}",
            "episode_id": episode_id,
            "session_id": session_id,
            "created_at": self._now(),
            "embedding_status": "pending",
        }
        self.episodes[episode_id] = {
            "episode_id": episode_id,
            "session_id": session_id,
            "role": payload.get("role", "user"),
            "content": payload.get("content", ""),
            "tags": payload.get("tags") or [],
            "metadata": payload.get("metadata") or {},
            "created_at": data["created_at"],
            "deleted": False,
            "embedding_status": "pending",
        }
        if idempotency_key:
            self.idempotency_cache[cache_key] = data
        return self._response(request, data)

    def _search(self, request: httpx.Request) -> httpx.Response:
        payload = self.json_body(request)
        query = str(payload.get("query") or "").lower()
        session_id = payload.get("session_id")
        tags = set(payload.get("tags") or [])
        filters = payload.get("tag_filters") or []
        limit = int(payload.get("limit") or 20)
        results: list[dict[str, Any]] = []

        for episode in self.episodes.values():
            if episode["deleted"]:
                continue
            if session_id and episode["session_id"] != session_id:
                continue
            if tags and not tags.intersection(set(episode["tags"])):
                continue
            if not self._matches_filters(episode["tags"], filters):
                continue
            haystack = f"{episode['content']} {' '.join(episode['tags'])}".lower()
            if query and query not in haystack and not any(token in haystack for token in query.split()):
                continue
            results.append(
                {
                    "episode_id": episode["episode_id"],
                    "content": episode["content"],
                    "role": episode["role"],
                    "score": 1.0,
                    "created_at": episode["created_at"],
                    "tags": episode["tags"],
                }
            )

        return self._response(
            request,
            {
                "request_id": "req-search-1",
                "results": results[:limit],
                "total": min(len(results), limit),
                "query_time_ms": 2,
            },
        )

    def _history(self, request: httpx.Request, session_id: str) -> httpx.Response:
        limit = int(request.url.params.get("limit", "50"))
        items = [
            {
                "episode_id": episode["episode_id"],
                "session_id": episode["session_id"],
                "role": episode["role"],
                "content": episode["content"],
                "created_at": episode["created_at"],
                "tags": episode["tags"],
                "metadata": episode["metadata"],
                "embedding_status": episode["embedding_status"],
            }
            for episode in self.episodes.values()
            if not episode["deleted"] and episode["session_id"] == session_id
        ]
        return self._response(request, {"episodes": items[:limit]})

    def _forget_episode(self, request: httpx.Request, episode_id: str) -> httpx.Response:
        if episode_id in self.episodes:
            self.episodes[episode_id]["deleted"] = True
        return self._response(request, {"deleted": True, "episode_id": episode_id})

    def _forget_session(self, request: httpx.Request, session_id: str) -> httpx.Response:
        deleted = 0
        for episode in self.episodes.values():
            if episode["session_id"] == session_id and not episode["deleted"]:
                episode["deleted"] = True
                deleted += 1
        return self._response(request, {"deleted_count": deleted, "session_id": session_id})

    def _checkpoint(self, request: httpx.Request, session_id: str) -> httpx.Response:
        idempotency_key = request.headers.get("Idempotency-Key")
        cache_key = (f"POST:/sessions/{session_id}/checkpoint", idempotency_key or "")
        if idempotency_key and cache_key in self.idempotency_cache:
            return self._response(request, self.idempotency_cache[cache_key])

        self._checkpoint_counter += 1
        checkpoint_id = f"cp-{self._checkpoint_counter}"
        history = [
            episode["episode_id"]
            for episode in self.episodes.values()
            if not episode["deleted"] and episode["session_id"] == session_id
        ]
        data = {
            "checkpoint_id": checkpoint_id,
            "created_at": self._now(),
            "message_count": len(history),
        }
        self.checkpoints[checkpoint_id] = {
            **data,
            "session_id": session_id,
            "snapshot": list(history),
        }
        if idempotency_key:
            self.idempotency_cache[cache_key] = data
        return self._response(request, data)

    def _restore(self, request: httpx.Request, session_id: str) -> httpx.Response:
        payload = self.json_body(request)
        checkpoint_id = str(payload.get("checkpoint_id"))
        checkpoint = self.checkpoints[checkpoint_id]
        return self._response(
            request,
            {
                "restored": True,
                "session_id": session_id,
                "checkpoint_id": checkpoint_id,
                "restored_message_count": len(checkpoint["snapshot"]),
            },
        )

    def _list_checkpoints(self, request: httpx.Request, session_id: str) -> httpx.Response:
        checkpoints = [
            {
                "checkpoint_id": checkpoint["checkpoint_id"],
                "created_at": checkpoint["created_at"],
                "message_count": checkpoint["message_count"],
            }
            for checkpoint in self.checkpoints.values()
            if checkpoint["session_id"] == session_id
        ]
        return self._response(request, {"checkpoints": checkpoints})

    def _response(self, request: httpx.Request, data: dict[str, Any]) -> httpx.Response:
        return httpx.Response(200, request=request, json={"data": data})

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _matches_filters(tags: list[str], filters: list[dict[str, Any]]) -> bool:
        if not filters:
            return True
        for filter_item in filters:
            key = str(filter_item.get("key") or "")
            op = str(filter_item.get("op") or "eq")
            value = filter_item.get("value")
            prefix = f"{key}:"
            matching = [tag for tag in tags if tag.startswith(prefix)]
            if op == "exists" and not matching:
                return False
            if op == "eq" and value is not None and f"{key}:{value}" not in tags:
                return False
            if op == "prefix" and value is not None and not any(
                tag.startswith(f"{key}:{value}") for tag in tags
            ):
                return False
        return True
