# Episodes

An episode is a single durable memory record. It stores content, role, timestamps, tags, optional metadata, and embedding lifecycle state.

## Episode shape

```python
from remembr import Episode

example = Episode(
    episode_id="0f8fad5b-d9cb-469f-a165-70867728950e",
    session_id="7dd6d5d0-cf89-4e9a-8f56-761e0f0f2df1",
    role="assistant",
    content="Suggested a staged rollout for the feature flag.",
    created_at="2026-04-22T10:00:00Z",
    tags=["kind:decision", "feature:flags"],
    metadata={"ticket": "REM-42"},
    embedding_status="ready",
)
```

## Design rules

- Episodes are append-only. Corrections are usually new episodes, not updates.
- Tags are plain strings, but structured `key:value` tags unlock `tag_filters`.
- `embedding_status` is `pending`, `ready`, or `failed`.
- Search results hide soft-deleted episodes automatically.

