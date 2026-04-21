"""Pydantic models used by the Remembr Python SDK."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class TagFilter(BaseModel):
    """Structured tag filter for ``key:value`` tag matching.

    Examples::

        TagFilter(key="category", value="science", op="eq")   # tags contain 'category:science'
        TagFilter(key="score", value="0.8", op="gte")          # numeric score >= 0.8
        TagFilter(key="source", op="exists")                   # any 'source:*' tag present
        TagFilter(key="topic", value="ai", op="prefix")        # tags starting with 'topic:ai'
    """

    key: str = Field(..., min_length=1)
    value: str | None = None
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "exists", "prefix"] = "eq"

    @model_validator(mode="after")
    def _validate(self) -> "TagFilter":
        if self.op in ("gt", "gte", "lt", "lte"):
            if self.value is None:
                raise ValueError(f"op={self.op!r} requires a numeric value (key={self.key!r})")
            try:
                float(self.value)
            except ValueError:
                raise ValueError(
                    f"op={self.op!r} requires a numeric value; got {self.value!r} for key={self.key!r}"
                )
        if self.op == "prefix" and self.value is None:
            raise ValueError(f"op='prefix' requires a value (key={self.key!r})")
        return self

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"key": self.key, "op": self.op}
        if self.value is not None:
            d["value"] = self.value
        return d


class Session(BaseModel):
    request_id: str
    session_id: str
    org_id: str
    created_at: datetime
    metadata: dict[str, Any] | None = None


class Episode(BaseModel):
    episode_id: str
    session_id: str | None = None
    role: str
    content: str
    created_at: datetime
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class SearchResult(BaseModel):
    episode_id: str
    content: str
    role: str
    score: float
    created_at: datetime
    tags: list[str] = Field(default_factory=list)


class MemoryQueryResult(BaseModel):
    request_id: str
    results: list[SearchResult]
    total: int
    query_time_ms: int


class CheckpointInfo(BaseModel):
    checkpoint_id: str
    created_at: datetime
    message_count: int
