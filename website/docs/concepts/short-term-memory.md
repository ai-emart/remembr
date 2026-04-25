# Short-Term Memory

Short-term memory is the fast working set that powers current-context retrieval, token budgeting, and checkpoint/restore flows.

## What it is not

It is not a replacement for long-term episodic memory. Think of it as the active conversation window, while episodes are the durable record.

## What it enables

- Windowed session retrieval through `GET /sessions/{session_id}`
- Checkpoint creation for long workflows
- Restore after crashes or branching
- Token usage summaries for orchestration layers

## Typical flow

1. Create a session.
2. Store episodes while the conversation progresses.
3. Checkpoint when you reach a useful boundary.
4. Restore later if you need to rewind the short-term window.

