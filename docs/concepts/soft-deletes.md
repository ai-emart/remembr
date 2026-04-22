# Soft Deletes

Deletes are soft by default. The episode disappears from search and history queries, but the underlying record can still be restored until the retention window is purged.

## Why this exists

- Safer operator experience
- Human error recovery
- Auditability
- GDPR and data lifecycle workflows

## Endpoints

- `DELETE /memory/{episode_id}`
- `DELETE /memory/session/{session_id}`
- `DELETE /memory/user/{user_id}`
- `POST /memory/{episode_id}/restore`
- `DELETE /memory/{episode_id}/hard`

## Behavior

- Search ignores soft-deleted episodes automatically.
- Restore brings the episode back into normal query paths.
- Hard delete is permanent.

