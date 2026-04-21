# API Reference

Base URL: `http://localhost:8000/api/v1`

Auth:
- **Bearer JWT** for `/auth/*`, `/api-keys/*`, and all memory/session APIs.
- **Bearer API key** is also supported by memory/session routes through auth middleware.

All responses use a standard envelope:

```json
{
  "data": {},
  "request_id": "req_..."
}
```

Errors follow a structured shape with `message`, optional `details.code`, and `request_id`.

---

## Idempotency

POST, PUT, and PATCH requests accept an optional `Idempotency-Key` header.  
When present, the server caches the response for **24 hours** and replays it
identically for any subsequent request carrying the same key from the same
authenticated identity — without re-executing the route.

**Rules:**
- Key must be **non-empty** and **≤ 255 characters**.
- Only **2xx** responses are cached. Error responses are never replayed.
- Replayed responses include the header `X-Idempotent-Replay: true`.
- Keys are scoped to the caller — two different API keys cannot collide even if
  they send the same key string.

**When to use it:**
Use idempotency keys on any write that must not be duplicated — storing an
episode after a transient network failure, creating a session on retry, etc.

```bash
# First call — executes the route and caches the response
curl -X POST "$BASE_URL/memory" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Idempotency-Key: my-unique-operation-id-001" \
  -H "Content-Type: application/json" \
  -d '{"role":"user","content":"Hello, world"}'

# Second call with the same key — returns the cached response immediately
curl -X POST "$BASE_URL/memory" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Idempotency-Key: my-unique-operation-id-001" \
  -H "Content-Type: application/json" \
  -d '{"role":"user","content":"Hello, world"}'
# → response header: X-Idempotent-Replay: true
```

---

## Auth

### POST `/auth/register`
Create organization + user and return access/refresh tokens.

**Auth required:** No

**Request body**
```json
{
  "email": "dev@example.com",
  "password": "strong-password",
  "org_name": "Acme AI"
}
```

**Response body (`201`)**
```json
{
  "data": {
    "access_token": "...",
    "refresh_token": "...",
    "token_type": "bearer"
  },
  "request_id": "..."
}
```

**Error codes:** `EMAIL_ALREADY_REGISTERED`

```bash
curl -X POST "$BASE_URL/auth/register" \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@example.com","password":"strong-password","org_name":"Acme AI"}'
```

### POST `/auth/login`
Authenticate an existing user.

**Auth required:** No

**Request body**
```json
{"email":"dev@example.com","password":"strong-password"}
```

**Response body (`200`)**
```json
{
  "data": {
    "access_token": "...",
    "refresh_token": "...",
    "token_type": "bearer"
  }
}
```

**Error codes:** `INVALID_CREDENTIALS`, `INACTIVE_USER`

```bash
curl -X POST "$BASE_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@example.com","password":"strong-password"}'
```

### POST `/auth/refresh`
Exchange refresh token for a new access token.

**Auth required:** No

**Request body**
```json
{"refresh_token":"..."}
```

**Response body (`200`)**
```json
{
  "data": {
    "access_token": "...",
    "token_type": "bearer"
  }
}
```

**Error codes:** `TOKEN_INVALIDATED`, `INVALID_TOKEN_TYPE`, `INVALID_TOKEN_PAYLOAD`

```bash
curl -X POST "$BASE_URL/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"'$REFRESH_TOKEN'"}'
```

### POST `/auth/logout`
Invalidate a refresh token.

**Auth required:** No

**Request body**
```json
{"refresh_token":"..."}
```

**Response body (`200`)**
```json
{"data":{"message":"Logged out"}}
```

**Error codes:** `INVALID_TOKEN_TYPE`

```bash
curl -X POST "$BASE_URL/auth/logout" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"'$REFRESH_TOKEN'"}'
```

### GET `/auth/me`
Get current user from access token.

**Auth required:** JWT bearer token

**Response body (`200`)**
```json
{
  "data": {
    "id": "uuid",
    "email": "dev@example.com",
    "org_id": "uuid",
    "team_id": null,
    "is_active": true,
    "created_at": "2026-01-01T00:00:00Z"
  }
}
```

```bash
curl "$BASE_URL/auth/me" -H "Authorization: Bearer $ACCESS_TOKEN"
```

---

## Sessions

### POST `/sessions`
Create a scoped session.

**Auth required:** JWT/API key

**Request body**
```json
{"metadata":{"source":"api-example"}}
```

**Response body (`201`)**
```json
{
  "data": {
    "request_id": "...",
    "session_id": "uuid",
    "org_id": "uuid",
    "created_at": "...",
    "metadata": {"source":"api-example"}
  }
}
```

```bash
curl -X POST "$BASE_URL/sessions" \
  -H "Authorization: Bearer $API_KEY_OR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"metadata":{"source":"api-example"}}'
```

### GET `/sessions`
List sessions in current scope.

**Auth required:** JWT/API key

**Query params:** `limit` (1-100), `offset` (>=0)

**Response body (`200`)**
```json
{
  "data": {
    "request_id": "...",
    "sessions": [
      {
        "session_id": "uuid",
        "created_at": "...",
        "metadata": {},
        "message_count": 10
      }
    ],
    "total": 1,
    "limit": 20,
    "offset": 0
  }
}
```

```bash
curl "$BASE_URL/sessions?limit=20&offset=0" -H "Authorization: Bearer $API_KEY_OR_TOKEN"
```

### GET `/sessions/{session_id}`
Get session details + short-term window messages.

**Auth required:** JWT/API key

**Response body (`200`)** includes `session`, `messages`, and `token_usage`.

**Error codes:** `SESSION_NOT_FOUND`

```bash
curl "$BASE_URL/sessions/$SESSION_ID" -H "Authorization: Bearer $API_KEY_OR_TOKEN"
```

### GET `/sessions/{session_id}/history`
Get episodic history for session.

**Auth required:** JWT/API key

**Query params:** `limit` (1-100), `offset` (>=0)

**Error codes:** `SESSION_NOT_FOUND`

```bash
curl "$BASE_URL/sessions/$SESSION_ID/history?limit=50&offset=0" \
  -H "Authorization: Bearer $API_KEY_OR_TOKEN"
```

### POST `/sessions/{session_id}/checkpoint`
Create checkpoint from short-term memory window.

**Auth required:** JWT/API key

**Response body (`201`)**
```json
{
  "data": {
    "request_id": "...",
    "checkpoint_id": "uuid",
    "created_at": "...",
    "message_count": 5
  }
}
```

**Error codes:** `SESSION_NOT_FOUND`, `CHECKPOINT_NOT_FOUND`

```bash
curl -X POST "$BASE_URL/sessions/$SESSION_ID/checkpoint" \
  -H "Authorization: Bearer $API_KEY_OR_TOKEN"
```

### POST `/sessions/{session_id}/restore`
Restore short-term memory from checkpoint.

**Auth required:** JWT/API key

**Request body**
```json
{"checkpoint_id":"uuid"}
```

**Response body (`200`)**
```json
{
  "data": {
    "request_id": "...",
    "restored_message_count": 5,
    "checkpoint_created_at": "..."
  }
}
```

**Error codes:** `SESSION_NOT_FOUND`, `CHECKPOINT_NOT_FOUND`

```bash
curl -X POST "$BASE_URL/sessions/$SESSION_ID/restore" \
  -H "Authorization: Bearer $API_KEY_OR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"checkpoint_id":"'$CHECKPOINT_ID'"}'
```

### GET `/sessions/{session_id}/checkpoints`
List session checkpoints.

**Auth required:** JWT/API key

```bash
curl "$BASE_URL/sessions/$SESSION_ID/checkpoints" \
  -H "Authorization: Bearer $API_KEY_OR_TOKEN"
```

---

## Memory

### POST `/memory`
Store episodic memory (optionally attach to session).

**Auth required:** JWT/API key

**Request body**
```json
{
  "role": "user",
  "content": "Remember to send weekly KPI reports on Friday.",
  "session_id": "uuid-optional",
  "tags": ["kpi", "reporting"],
  "metadata": {"source": "agent"}
}
```

**Response body (`201`)**
```json
{
  "data": {
    "request_id": "...",
    "episode_id": "uuid",
    "session_id": "uuid",
    "created_at": "...",
    "token_count": 11
  }
}
```

**Error codes:** `SESSION_NOT_FOUND`

```bash
curl -X POST "$BASE_URL/memory" \
  -H "Authorization: Bearer $API_KEY_OR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role":"user","content":"Remember to send weekly KPI reports on Friday.","session_id":"'$SESSION_ID'"}'
```

### POST `/memory/search`
Search memory via semantic/hybrid/filter strategies.

**Auth required:** JWT/API key

**Request body**
```json
{
  "query": "When do I send KPI reports?",
  "session_id": "uuid-optional",
  "role": null,
  "tags": ["kpi"],
  "tag_filters": [
    { "key": "category", "value": "work", "op": "eq" },
    { "key": "score",    "value": "0.7",  "op": "gte" }
  ],
  "from_time": null,
  "to_time": null,
  "limit": 20,
  "offset": 0
}
```

**`tag_filters` — structured tag filters**

Each filter matches episodes whose `tags` array contains a `key:value` entry that
satisfies the given operator.  Flat string tags (no colon) are also supported via
`eq` and `ne`.  All filters are ANDed together.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key` | string | Yes | Tag key (the part before `:` in `key:value` tags). |
| `value` | string | Conditional | Tag value. Required for `gt`, `gte`, `lt`, `lte`, `prefix`. |
| `op` | string | No (default `eq`) | One of: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `exists`, `prefix`. |

**Operators:**

| `op` | Meaning |
|------|---------|
| `eq` | Episode has tag `key:value` (or any `key:*` tag if `value` is omitted). |
| `ne` | Episode does NOT have tag `key:value`. |
| `exists` | Episode has at least one `key:*` tag. |
| `prefix` | Episode has a tag starting with `key:value`. |
| `gt` / `gte` / `lt` / `lte` | Numeric comparison on the value portion of `key:value`. |

**Response body (`200`)** includes `results`, `total`, `query_time_ms`.

**Error codes:** `INVALID_TIME_RANGE`

```bash
# Simple flat-tag search (backward-compatible)
curl -X POST "$BASE_URL/memory/search" \
  -H "Authorization: Bearer $API_KEY_OR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"When do I send KPI reports?","session_id":"'$SESSION_ID'","limit":5}'

# Structured tag filter: category=work AND score>=0.7
curl -X POST "$BASE_URL/memory/search" \
  -H "Authorization: Bearer $API_KEY_OR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "KPI reports",
    "tag_filters": [
      {"key":"category","value":"work","op":"eq"},
      {"key":"score","value":"0.7","op":"gte"}
    ]
  }'
```

### GET `/memory/diff`
List new memories between timestamps.

**Auth required:** JWT/API key

**Query params:**
- `from_time` (required ISO-8601)
- `to_time` (required ISO-8601)
- `session_id`, `user_id`, `role`, `tags` (optional)

**Error codes:** `INVALID_TIME_RANGE`, `SESSION_NOT_FOUND`

```bash
curl "$BASE_URL/memory/diff?from_time=2026-01-01T00:00:00Z&to_time=2026-01-02T00:00:00Z&session_id=$SESSION_ID" \
  -H "Authorization: Bearer $API_KEY_OR_TOKEN"
```

---

## Management (Forgetting + API keys + service)

### DELETE `/memory/{episode_id}`
Delete one episode.

**Auth required:** JWT/API key

**Error codes:** `EPISODE_NOT_FOUND`

```bash
curl -X DELETE "$BASE_URL/memory/$EPISODE_ID" -H "Authorization: Bearer $API_KEY_OR_TOKEN"
```

### DELETE `/memory/session/{session_id}`
Delete all episodes in a session.

**Auth required:** JWT/API key

**Error codes:** `SESSION_NOT_FOUND`

```bash
curl -X DELETE "$BASE_URL/memory/session/$SESSION_ID" -H "Authorization: Bearer $API_KEY_OR_TOKEN"
```

### DELETE `/memory/user/{user_id}`
Delete all sessions + episodes for a user (org-level authority required).

**Auth required:** Org-level JWT/API key (no user/agent scoping)

**Error codes:** `ORG_LEVEL_REQUIRED`

```bash
curl -X DELETE "$BASE_URL/memory/user/$USER_ID" -H "Authorization: Bearer $API_KEY_OR_TOKEN"
```

### POST `/api-keys`
Create API key.

**Auth required:** JWT bearer token

**Request body**
```json
{
  "name": "ci-e2e-key",
  "agent_id": null,
  "expires_at": null
}
```

```bash
curl -X POST "$BASE_URL/api-keys" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"ci-e2e-key"}'
```

### GET `/api-keys`
List API keys in org.

**Auth required:** JWT bearer token

```bash
curl "$BASE_URL/api-keys" -H "Authorization: Bearer $ACCESS_TOKEN"
```

### DELETE `/api-keys/{key_id}`
Revoke API key.

**Auth required:** JWT bearer token

**Error codes:** `API_KEY_NOT_FOUND`

```bash
curl -X DELETE "$BASE_URL/api-keys/$KEY_ID" -H "Authorization: Bearer $ACCESS_TOKEN"
```

---

## Export

### GET `/export`
Stream all episodes for the authenticated scope as JSON or CSV without buffering
the entire dataset in memory.

**Auth required:** API key or JWT bearer token

**Query parameters**

| Parameter        | Type      | Default | Description |
|------------------|-----------|---------|-------------|
| `format`         | `json\|csv` | `json`  | Output format. |
| `from_date`      | ISO 8601  | —       | Lower bound for `created_at`. |
| `to_date`        | ISO 8601  | —       | Upper bound for `created_at`. |
| `session_id`     | UUID      | —       | Limit to a single session. |
| `include_deleted`| bool      | `false` | Include soft-deleted episodes. |

**JSON response** — streaming `application/json` array, one object per episode:
```json
[
  {"id":"…","session_id":"…","role":"user","content":"…","tags":[],"metadata":{},"created_at":"…","embedding_status":"ready"},
  …
]
```

**CSV response** — streaming `text/csv` with headers:
```
id,session_id,role,content,tags,metadata,created_at,embedding_status
```
Tags are semicolon-joined; metadata is JSON-encoded.

```bash
# JSON export
curl "$BASE_URL/export" \
  -H "Authorization: Bearer $API_KEY" \
  --output export.json

# CSV export with date filter
curl "$BASE_URL/export?format=csv&from_date=2026-01-01T00:00:00Z" \
  -H "Authorization: Bearer $API_KEY" \
  --output export.csv
```

---

### GET `/health`
Service health status.

**Auth required:** No

```bash
curl "$BASE_URL/health"
```

### GET `/me`
Auth middleware context (`org_id`, `user_id`, `agent_id`, `auth_method`).

**Auth required:** JWT/API key

```bash
curl "$BASE_URL/me" -H "Authorization: Bearer $API_KEY_OR_TOKEN"
```

---

## Error model

Common HTTP statuses:
- `400` validation failures
- `401/403` authentication or authorization issues
- `404` not found
- `409` conflict
- `429` rate limited
- `5xx` transient server errors

Common application error codes used by these endpoints:
- `EMAIL_ALREADY_REGISTERED`
- `INVALID_CREDENTIALS`
- `INACTIVE_USER`
- `TOKEN_INVALIDATED`
- `INVALID_TOKEN_TYPE`
- `INVALID_TOKEN_PAYLOAD`
- `SESSION_NOT_FOUND`
- `CHECKPOINT_NOT_FOUND`
- `EPISODE_NOT_FOUND`
- `INVALID_TIME_RANGE`
- `ORG_LEVEL_REQUIRED`
- `API_KEY_NOT_FOUND`
