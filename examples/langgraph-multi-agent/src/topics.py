"""Topic helpers and sample topics for the LangGraph example."""

from __future__ import annotations

import re

SAMPLE_TOPICS = [
    "Why are transformer models dominant in 2026?",
    "What trade-offs make retrieval-augmented generation still useful in 2026?",
    "How should teams evaluate agent memory systems before production rollout?",
]


def topic_slug(topic: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    return slug or "topic"
