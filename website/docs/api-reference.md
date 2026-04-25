# API Reference

This reference documents the current V1 API surface exposed by the FastAPI server under `/api/v1`.

## Conventions

- Base URL: `http://localhost:8000/api/v1`
- Auth: `Authorization: Bearer <api-key-or-access-token>`
- Response envelope: `{ "success": true, "data": ..., "request_id": "..." }`
- Timestamps are ISO 8601 UTC strings
- Soft-deleted memories do not appear in normal search results

## Health

### `GET /health`

Public health probe for the server.

Response shape:

```json
{
  "status": "ok"
}
```

## Authentication

### `POST /auth/register`

Create a new organization and initial user.

Request body:

```json
{
  "email": "user@example.com",
  "password": "correct-horse-battery-staple",
  "org_name": "Acme"
}
```

Response data:

```json
{
  "access_token": "jwt",
  "refresh_token": "jwt",
  "token_type": "bearer"
}
```

### `POST /auth/login`

Request body:

```json
{
  "email": "user@example.com",
  "password": "correct-horse-battery-staple"
}
```

Response data matches `register`.

### `POST /auth/refresh`

Request body:

```json
{
  "refresh_token": "jwt"
}
```

Response data:

```json
{
  "access_token": "jwt",
  "token_type": "bearer"
}
```

### `POST /auth/logout`

Invalidates a refresh token.

Request body:

```json
{
  "refresh_token": "jwt"
}
```

### `GET /auth/me`

Returns the authenticated user.

## API Keys

### `POST /api-keys`

Create an API key for SDK and adapter use.

Request body:

```json
{
  "name": "langgraph-dev",
  "agent_id": null,
  "expires_at": null
}
```

Response data:

```json
{
  "id": "uuid",
  "name": "langgraph-dev",
  "api_key": "rk_...",
  "org_id": "uuid",
  "user_id": "uuid",
  "agent_id": null,
  "expires_at": null,
  "created_at": "2026-04-22T10:00:00Z"
}
```

### `GET /api-keys`

List keys visible to the current org.

### `DELETE /api-keys/{key_id}`

Revoke a key.

## Sessions

### `POST /sessions`

Create a session.

Request body:

```json
{
  "metadata": {
    "source": "docs",
    "thread": "support-42"
  }
}
```

Response data:

```json
{
  "request_id": "req_123",
  "session_id": "uuid",
  "org_id": "uuid",
  "created_at": "2026-04-22T10:00:00Z",
  "metadata": {
    "source": "docs",
    "thread": "support-42"
  }
}
```

Parameters:

- `metadata`: optional JSON object
- `Idempotency-Key` header: optional

### `GET /sessions`

List sessions in the current scope.

Query params:

- `limit`: integer, default `20`, max implementation-dependent
- `offset`: integer, default `0`

### `GET /sessions/{session_id}`

Returns session metadata, short-term window messages, and token usage summary.

Response data:

```json
{
  "request_id": "req_123",
  "session": {
    "session_id": "uuid",
    "org_id": "uuid",
    "created_at": "2026-04-22T10:00:00Z",
    "metadata": {}
  },
  "messages": [
    {
      "role": "user",
      "content": "Question",
      "tokens": 3,
      "priority_score": 1.0,
      "timestamp": "2026-04-22T10:00:00Z"
    }
  ],
  "token_usage": {
    "message_count": 1,
    "estimated_tokens": 3
  }
}
```

### `GET /sessions/{session_id}/history`

Returns stored episodes for a session.

Query params:

- `limit`: integer, default `50`
- `offset`: integer, default `0`

### `POST /sessions/{session_id}/checkpoint`

Create a short-term memory checkpoint.

Headers:

- `Idempotency-Key`: optional and recommended for orchestrators

Response data:

```json
{
  "request_id": "req_123",
  "checkpoint_id": "uuid",
  "created_at": "2026-04-22T10:00:00Z",
  "message_count": 12
}
```

### `GET /sessions/{session_id}/checkpoints`

List checkpoints for a session.

### `POST /sessions/{session_id}/restore`

Restore the short-term window from a checkpoint.

Request body:

```json
{
  "checkpoint_id": "uuid"
}
```

Response data:

```json
{
  "request_id": "req_123",
  "restored_message_count": 12,
  "checkpoint_created_at": "2026-04-22T10:00:00Z"
}
```

### `GET /sessions/{session_id}/embedding-status`

Aggregate embedding status for all episodes in the session.

Response data:

```json
{
  "session_id": "uuid",
  "pending": 1,
  "ready": 8,
  "failed": 0,
  "total": 9
}
```

## Memory

### `POST /memory`

Store an episode.

Request body:

```json
{
  "role": "user",
  "content": "Customer prefers Friday summaries.",
  "session_id": "uuid",
  "tags": ["kind:preference", "customer:ada"],
  "metadata": {
    "source": "langgraph"
  }
}
```

Response data:

```json
{
  "request_id": "req_123",
  "episode_id": "uuid",
  "session_id": "uuid",
  "created_at": "2026-04-22T10:00:00Z",
  "token_count": 4,
  "embedding_status": "pending"
}
```

Parameters:

- `role`: required string
- `content`: required string
- `session_id`: optional UUID
- `tags`: optional string array
- `metadata`: optional object
- `Idempotency-Key` header: optional

### `POST /memory/search`

Search episodes.

Request body:

```json
{
  "query": "When should summaries be sent?",
  "session_id": "uuid",
  "tags": ["customer:ada"],
  "tag_filters": [
    {"key": "kind", "value": "preference", "op": "eq"}
  ],
  "from_time": "2026-04-01T00:00:00Z",
  "to_time": "2026-04-30T23:59:59Z",
  "limit": 10,
  "offset": 0,
  "search_mode": "hybrid",
  "weights": {
    "semantic": 0.6,
    "keyword": 0.3,
    "recency": 0.1
  }
}
```

Search params:

- `query`: optional string in filter-only paths, normally required for retrieval
- `session_id`: optional UUID
- `role`: optional role filter
- `tags`: exact-match flat tags
- `tag_filters`: structured filters with `key`, optional `value`, and `op`
- `from_time`, `to_time`: optional timestamps
- `limit`: `1..100`
- `offset`: `>=0`
- `search_mode`: `semantic`, `keyword`, or `hybrid`
- `weights`: hybrid weights that must sum to `1.0`

Response data:

```json
{
  "request_id": "req_123",
  "results": [
    {
      "episode_id": "uuid",
      "content": "Customer prefers Friday summaries.",
      "role": "user",
      "score": 0.93,
      "created_at": "2026-04-22T10:00:00Z",
      "tags": ["kind:preference", "customer:ada"]
    }
  ],
  "total": 1,
  "query_time_ms": 14
}
```

### `DELETE /memory/{episode_id}`

Soft-delete one episode.

Response data:

```json
{
  "request_id": "req_123",
  "deleted": true,
  "episode_id": "uuid",
  "soft": true,
  "restorable_until": "2026-05-22T10:00:00Z"
}
```

### `DELETE /memory/session/{session_id}`

Soft-delete all episodes in a session.

### `DELETE /memory/user/{user_id}`

Soft-delete all episodes and sessions for a user within the current org.

### `DELETE /memory/{episode_id}/hard`

Permanently delete an episode.

### `POST /memory/{episode_id}/restore`

Restore a previously soft-deleted episode.

### `GET /memory/{episode_id}/status`

Return embedding status for a single episode.

Response data:

```json
{
  "episode_id": "uuid",
  "embedding_status": "ready",
  "embedding_generated_at": "2026-04-22T10:01:00Z",
  "embedding_error": null
}
```

### `GET /memory/diff`

Return episodes added during a time period.

Typical query params:

- `from_time`
- `to_time`
- `session_id`
- `limit`

Response data:

```json
{
  "request_id": "req_123",
  "added": [
    {
      "episode_id": "uuid",
      "session_id": "uuid",
      "role": "assistant",
      "content": "Added a rollback warning.",
      "created_at": "2026-04-22T10:00:00Z",
      "tags": ["kind:feedback"]
    }
  ],
  "period": {
    "from_time": "2026-04-22T09:00:00Z",
    "to_time": "2026-04-22T11:00:00Z"
  },
  "count": 1
}
```

## Export

### `GET /export`

Export episodes as streamed JSON or CSV.

Query params:

- `format`: `json` or `csv`
- `from_date`: optional
- `to_date`: optional
- `session_id`: optional
- `include_deleted`: `true` or `false`

## Webhooks

Supported events:

- `memory.stored`
- `embedding.ready`
- `session.created`
- `memory.deleted`
- `checkpoint.created`

### `POST /webhooks`

Request body:

```json
{
  "url": "https://example.com/remembr",
  "events": ["memory.stored", "memory.deleted"],
  "active": true
}
```

Response data includes the generated secret on create and rotate:

```json
{
  "id": "uuid",
  "org_id": "uuid",
  "url": "https://example.com/remembr",
  "events": ["memory.stored"],
  "active": true,
  "created_at": "2026-04-22T10:00:00Z",
  "updated_at": "2026-04-22T10:00:00Z",
  "last_delivery_at": null,
  "last_delivery_status": null,
  "failure_count": 0,
  "secret": "hex-string"
}
```

### `GET /webhooks`

List org webhooks.

### `GET /webhooks/{webhook_id}`

Get one webhook.

### `PATCH /webhooks/{webhook_id}`

Update `url`, `events`, or `active`.

### `DELETE /webhooks/{webhook_id}`

Soft-delete and disable a webhook.

### `POST /webhooks/{webhook_id}/rotate-secret`

Generate a new signing secret.

### `GET /webhooks/{webhook_id}/deliveries`

List recent deliveries.

### `POST /webhooks/{webhook_id}/test`

Enqueue a `webhook.test` delivery.

## SDK mapping

Python SDK methods map to the API like this:

- `create_session()` -> `POST /sessions`
- `get_session()` -> `GET /sessions/{session_id}`
- `list_sessions()` -> `GET /sessions`
- `store()` -> `POST /memory`
- `search()` -> `POST /memory/search`
- `get_session_history()` -> `GET /sessions/{session_id}/history`
- `checkpoint()` -> `POST /sessions/{session_id}/checkpoint`
- `restore()` -> `POST /sessions/{session_id}/restore`
- `list_checkpoints()` -> `GET /sessions/{session_id}/checkpoints`
- `forget_episode()` -> `DELETE /memory/{episode_id}`
- `forget_session()` -> `DELETE /memory/session/{session_id}`
- `forget_user()` -> `DELETE /memory/user/{user_id}`
- `export()` -> `GET /export`
- `client.webhooks.*` -> `/webhooks/*`

