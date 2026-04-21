"""Core Remembr SDK client implementation."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any, AsyncIterator

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from .exceptions import AuthenticationError, NotFoundError, RateLimitError, RemembrError, ServerError
from .models import CheckpointInfo, Episode, MemoryQueryResult, Session, TagFilter


class _RetryableServerError(ServerError):
    """Internal exception used to trigger retries for transient failures."""


class RemembrClient:
    """Remembr API client with async-first APIs and sync wrappers."""

    VALID_SEARCH_MODES = {"semantic", "hybrid", "filter_only"}

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "http://localhost:8000/api/v1",
        timeout: float = 30,
    ) -> None:
        resolved_api_key = api_key or os.getenv("REMEMBR_API_KEY")
        if not resolved_api_key:
            raise AuthenticationError(
                "Missing API key. Pass `api_key=` or set REMEMBR_API_KEY environment variable."
            )

        self.api_key = resolved_api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "RemembrClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        await self.aclose()

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def aclose(self) -> None:
        """Close underlying HTTP resources for the async client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def arequest(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Perform a raw API request and return the `data` payload.

        Args:
            method: HTTP method name, such as ``"GET"`` or ``"POST"``.
            path: API path relative to ``base_url``.
            params: Optional query parameters.
            json: Optional JSON request body.

        Returns:
            The deserialized response payload (typically the API `data` object).
        """
        client = await self._ensure_client()
        extra_headers: dict[str, str] = {}
        if idempotency_key is not None:
            extra_headers["Idempotency-Key"] = idempotency_key

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(4),  # initial + 3 retries
                wait=wait_exponential(multiplier=1, min=1, max=4),
                retry=retry_if_exception_type((_RetryableServerError, httpx.TimeoutException)),
                reraise=True,
            ):
                with attempt:
                    response = await client.request(
                        method=method, url=path, params=params, json=json, headers=extra_headers
                    )
                    if response.status_code == 429 or 500 <= response.status_code <= 599:
                        exc = self._to_exception(response)
                        raise _RetryableServerError(
                            str(exc),
                            status_code=response.status_code,
                            code=getattr(exc, "code", None),
                            details=getattr(exc, "details", None),
                            request_id=getattr(exc, "request_id", None),
                        )

                    if response.status_code >= 400:
                        raise self._to_exception(response)

                    try:
                        body = response.json()
                    except ValueError as err:
                        raise ServerError(
                            "Failed to parse JSON response from Remembr API.",
                            status_code=response.status_code,
                        ) from err

                    if isinstance(body, dict) and "data" in body:
                        return body["data"]

                    if isinstance(body, dict):
                        return body

                    raise ServerError(
                        "Unexpected response type returned by Remembr API.",
                        status_code=response.status_code,
                    )
        except httpx.TimeoutException as err:
            raise ServerError("Request to Remembr API timed out.", code="TIMEOUT") from err
        except _RetryableServerError as err:
            if err.status_code == 429:
                raise RateLimitError(
                    err.message,
                    status_code=err.status_code,
                    code=err.code,
                    details=err.details,
                    request_id=err.request_id,
                ) from err
            raise ServerError(
                err.message,
                status_code=err.status_code,
                code=err.code,
                details=err.details,
                request_id=err.request_id,
            ) from err
        except httpx.HTTPError as err:
            raise ServerError("HTTP communication error with Remembr API.") from err

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Synchronous wrapper over :meth:`arequest` using ``asyncio.run()``.

        Args:
            method: HTTP method name, such as ``"GET"`` or ``"POST"``.
            path: API path relative to ``base_url``.
            params: Optional query parameters.
            json: Optional JSON request body.

        Returns:
            The deserialized response payload (typically the API `data` object).
        """
        return asyncio.run(self.arequest(method, path, params=params, json=json))

    async def create_session(
        self,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Session:
        """Create a new memory session.

        Args:
            metadata: Optional metadata dictionary stored alongside the created session.
            idempotency_key: Optional idempotency key to make this request safe to retry.

        Returns:
            A :class:`~remembr.models.Session` object describing the newly created session.
        """
        payload = {"metadata": metadata or {}}
        data = await self.arequest("POST", "/sessions", json=payload, idempotency_key=idempotency_key)
        return Session.model_validate(data)

    async def get_session(self, session_id: str) -> Session:
        """Fetch metadata for a session by ID.

        Args:
            session_id: The target session identifier.

        Returns:
            A :class:`~remembr.models.Session` object containing session details.
        """
        self._require_non_empty(session_id, "session_id")
        data = await self.arequest("GET", f"/sessions/{session_id}")
        session_data = data.get("session") if isinstance(data, dict) else None
        if not isinstance(session_data, dict):
            raise ServerError("Invalid session payload returned by Remembr API.")

        return Session.model_validate(
            {
                "request_id": str(data.get("request_id", "")),
                "session_id": session_data.get("session_id"),
                "org_id": session_data.get("org_id"),
                "created_at": session_data.get("created_at"),
                "metadata": session_data.get("metadata"),
            }
        )

    async def list_sessions(self, limit: int = 20, offset: int = 0) -> list[Session]:
        """List sessions for the authenticated scope.

        Args:
            limit: Maximum number of sessions to return.
            offset: Number of sessions to skip before returning results.

        Returns:
            A list of :class:`~remembr.models.Session` objects.
        """
        self._validate_pagination(limit=limit, offset=offset)
        data = await self.arequest("GET", "/sessions", params={"limit": limit, "offset": offset})
        sessions = data.get("sessions") if isinstance(data, dict) else None
        if not isinstance(sessions, list):
            raise ServerError("Invalid session list payload returned by Remembr API.")

        request_id = str(data.get("request_id", ""))
        org_id = str(data.get("org_id", ""))
        return [
            Session.model_validate(
                {
                    "request_id": request_id,
                    "session_id": item.get("session_id"),
                    "org_id": org_id,
                    "created_at": item.get("created_at"),
                    "metadata": item.get("metadata"),
                }
            )
            for item in sessions
            if isinstance(item, dict)
        ]

    async def store(
        self,
        content: str,
        role: str = "user",
        session_id: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> Episode:
        """Store a memory episode.

        Args:
            content: Episode content text to persist.
            role: Role label (for example ``"user"`` or ``"assistant"``).
            session_id: Optional session ID to associate with the episode.
            tags: Optional list of string tags.
            metadata: Optional metadata dictionary for the episode.
            idempotency_key: Optional idempotency key to make this request safe to retry.

        Returns:
            An :class:`~remembr.models.Episode` describing the stored memory.
        """
        self._require_non_empty(content, "content")
        self._require_non_empty(role, "role")
        if session_id is not None:
            self._require_non_empty(session_id, "session_id")

        payload: dict[str, Any] = {
            "content": content,
            "role": role,
            "tags": tags or [],
            "metadata": metadata or {},
        }
        if session_id:
            payload["session_id"] = session_id

        data = await self.arequest("POST", "/memory", json=payload, idempotency_key=idempotency_key)
        return Episode.model_validate(
            {
                "episode_id": data.get("episode_id"),
                "session_id": data.get("session_id"),
                "role": role,
                "content": content,
                "created_at": data.get("created_at"),
                "tags": tags or [],
                "metadata": metadata,
            }
        )

    async def search(
        self,
        query: str,
        session_id: str | None = None,
        tags: list[str] | None = None,
        tag_filters: list[TagFilter] | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        limit: int = 20,
        mode: str = "hybrid",
    ) -> MemoryQueryResult:
        """Search memory episodes.

        Args:
            query: Search text query.
            session_id: Optional session ID to scope the search.
            tags: Optional list of flat tag strings for exact-match filtering (backward-compatible).
            tag_filters: Optional structured tag filters with key, value, and comparison operator.
            from_time: Optional lower timestamp bound (inclusive).
            to_time: Optional upper timestamp bound (inclusive).
            limit: Maximum number of search results to return.
            mode: Search mode, one of ``semantic``, ``hybrid``, or ``filter_only``.

        Returns:
            A :class:`~remembr.models.MemoryQueryResult` object with matches and metadata.
        """
        self._require_non_empty(query, "query")
        if session_id is not None:
            self._require_non_empty(session_id, "session_id")
        if limit < 1:
            raise ValueError("limit must be greater than 0")
        if mode not in self.VALID_SEARCH_MODES:
            raise ValueError("mode must be one of: semantic, hybrid, filter_only")
        if from_time and to_time and from_time > to_time:
            raise ValueError("from_time must be less than or equal to to_time")

        payload: dict[str, Any] = {
            "query": query,
            "tags": tags,
            "limit": limit,
            "mode": mode,
        }
        if session_id:
            payload["session_id"] = session_id
        if from_time is not None:
            payload["from_time"] = from_time.isoformat()
        if to_time is not None:
            payload["to_time"] = to_time.isoformat()
        if tag_filters:
            payload["tag_filters"] = [tf.to_dict() for tf in tag_filters]

        data = await self.arequest("POST", "/memory/search", json=payload)
        return MemoryQueryResult.model_validate(data)

    async def get_session_history(self, session_id: str, limit: int = 50) -> list[Episode]:
        """Retrieve stored episodes for a given session.

        Args:
            session_id: The session identifier.
            limit: Maximum number of episodes to return.

        Returns:
            A list of :class:`~remembr.models.Episode` objects in API response order.
        """
        self._require_non_empty(session_id, "session_id")
        if limit < 1:
            raise ValueError("limit must be greater than 0")

        data = await self.arequest("GET", f"/sessions/{session_id}/history", params={"limit": limit})
        episodes = data.get("episodes") if isinstance(data, dict) else None
        if not isinstance(episodes, list):
            raise ServerError("Invalid session history payload returned by Remembr API.")
        return [Episode.model_validate(item) for item in episodes if isinstance(item, dict)]

    async def checkpoint(self, session_id: str) -> CheckpointInfo:
        """Create a checkpoint for a session context window.

        Args:
            session_id: Session identifier for which to create a checkpoint.

        Returns:
            A :class:`~remembr.models.CheckpointInfo` for the created checkpoint.
        """
        self._require_non_empty(session_id, "session_id")
        data = await self.arequest("POST", f"/sessions/{session_id}/checkpoint")
        return CheckpointInfo.model_validate(data)

    async def restore(self, session_id: str, checkpoint_id: str) -> dict[str, Any]:
        """Restore a session's short-term context from a checkpoint.

        Args:
            session_id: Session identifier to restore.
            checkpoint_id: Checkpoint identifier to restore from.

        Returns:
            A dictionary containing restore details from the API.
        """
        self._require_non_empty(session_id, "session_id")
        self._require_non_empty(checkpoint_id, "checkpoint_id")
        return await self.arequest(
            "POST",
            f"/sessions/{session_id}/restore",
            json={"checkpoint_id": checkpoint_id},
        )

    async def list_checkpoints(self, session_id: str) -> list[CheckpointInfo]:
        """List available checkpoints for a session.

        Args:
            session_id: Session identifier to inspect.

        Returns:
            A list of :class:`~remembr.models.CheckpointInfo` entries.
        """
        self._require_non_empty(session_id, "session_id")
        data = await self.arequest("GET", f"/sessions/{session_id}/checkpoints")
        checkpoints = data.get("checkpoints") if isinstance(data, dict) else None
        if not isinstance(checkpoints, list):
            raise ServerError("Invalid checkpoint list payload returned by Remembr API.")
        return [CheckpointInfo.model_validate(item) for item in checkpoints if isinstance(item, dict)]

    async def forget_episode(self, episode_id: str) -> dict[str, Any]:
        """Delete a single memory episode.

        Args:
            episode_id: Episode identifier to delete.

        Returns:
            A dictionary confirming deletion details.
        """
        self._require_non_empty(episode_id, "episode_id")
        return await self.arequest("DELETE", f"/memory/{episode_id}")

    async def forget_session(self, session_id: str) -> dict[str, Any]:
        """Delete all memory episodes in a session.

        Args:
            session_id: Session identifier whose memories should be removed.

        Returns:
            A dictionary summarizing deleted episode count.
        """
        self._require_non_empty(session_id, "session_id")
        return await self.arequest("DELETE", f"/memory/session/{session_id}")

    async def forget_user(self, user_id: str) -> dict[str, Any]:
        """Delete all memories and sessions for a user (org-scoped operation).

        Args:
            user_id: User identifier whose memory data should be removed.

        Returns:
            A dictionary summarizing deleted sessions and episodes.
        """
        self._require_non_empty(user_id, "user_id")
        return await self.arequest("DELETE", f"/memory/user/{user_id}")

    async def export(
        self,
        format: str = "json",
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        session_id: str | None = None,
        include_deleted: bool = False,
    ) -> AsyncIterator[dict[str, Any]] | bytes:
        """Export all episodes for the authenticated scope.

        Args:
            format: ``"json"`` (default) returns an ``AsyncIterator[dict]``; ``"csv"`` returns ``bytes``.
            from_date: Optional lower bound for ``created_at``.
            to_date: Optional upper bound for ``created_at``.
            session_id: Limit to a single session.
            include_deleted: Include soft-deleted episodes (default: False).

        Returns:
            An :class:`AsyncIterator[dict]` for JSON, or ``bytes`` for CSV.
        """
        if format not in ("json", "csv"):
            raise ValueError("format must be 'json' or 'csv'")

        params: dict[str, Any] = {"format": format, "include_deleted": str(include_deleted).lower()}
        if from_date is not None:
            params["from_date"] = from_date.isoformat()
        if to_date is not None:
            params["to_date"] = to_date.isoformat()
        if session_id is not None:
            params["session_id"] = session_id

        client = await self._ensure_client()
        url = "/export"
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        full_url = f"{url}?{qs}" if qs else url

        if format == "csv":
            response = await client.get(full_url)
            response.raise_for_status()
            return response.content

        # JSON: return an async iterator that streams objects
        return self._stream_json_export(client, full_url)

    async def _stream_json_export(
        self, client: httpx.AsyncClient, url: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Async generator that yields one episode dict per item in the streamed JSON array."""
        import json as _json

        async with client.stream("GET", url) as response:
            response.raise_for_status()
            buf = ""
            depth = 0
            in_str = False
            escape_next = False

            async for chunk in response.aiter_text():
                for ch in chunk:
                    if escape_next:
                        buf += ch
                        escape_next = False
                        continue
                    if ch == "\\" and in_str:
                        buf += ch
                        escape_next = True
                        continue
                    if ch == '"':
                        in_str = not in_str
                    if not in_str:
                        if ch == "{":
                            depth += 1
                        elif ch == "}":
                            depth -= 1

                    buf += ch

                    if depth == 0:
                        # Strip array brackets / commas / whitespace to find object boundary
                        candidate = buf.lstrip(" \t\n\r[],")
                        if candidate.startswith("{"):
                            obj_str = candidate.rstrip(" \t\n\r,")
                            if obj_str:
                                try:
                                    yield _json.loads(obj_str)
                                except _json.JSONDecodeError:
                                    pass
                            buf = ""
                        elif not candidate:
                            buf = ""  # only separators accumulated — clear

    @staticmethod
    def _require_non_empty(value: str, param_name: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{param_name} is required and must be a non-empty string")

    @staticmethod
    def _validate_pagination(limit: int, offset: int) -> None:
        if limit < 1:
            raise ValueError("limit must be greater than 0")
        if offset < 0:
            raise ValueError("offset must be greater than or equal to 0")

    @staticmethod
    def _to_exception(response: httpx.Response) -> RemembrError:
        status_code = response.status_code
        message = f"Remembr API request failed with status code {status_code}."
        code: str | None = None
        details: dict[str, Any] | None = None
        request_id: str | None = None

        try:
            payload = response.json()
            if isinstance(payload, dict):
                error = payload.get("error")
                if isinstance(error, dict):
                    message = str(error.get("message", message))
                    code = error.get("code") if isinstance(error.get("code"), str) else None
                    details = error.get("details") if isinstance(error.get("details"), dict) else None
                    request_id = (
                        error.get("request_id") if isinstance(error.get("request_id"), str) else None
                    )
        except ValueError:
            pass

        if status_code in (401, 403):
            return AuthenticationError(
                message, status_code=status_code, code=code, details=details, request_id=request_id
            )
        if status_code == 404:
            return NotFoundError(
                message, status_code=status_code, code=code, details=details, request_id=request_id
            )
        if status_code == 429:
            return RateLimitError(
                message, status_code=status_code, code=code, details=details, request_id=request_id
            )
        if 500 <= status_code <= 599:
            return ServerError(
                message, status_code=status_code, code=code, details=details, request_id=request_id
            )

        return RemembrError(
            message, status_code=status_code, code=code, details=details, request_id=request_id
        )
