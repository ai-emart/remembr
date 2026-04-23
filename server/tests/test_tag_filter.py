"""Tests for TagFilter model and build_tag_filter_sql / _matches_tag_filters."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.tag_filter import TagFilter, build_tag_filter_sql

# ── TagFilter validation ──────────────────────────────────────────────────────


class TestTagFilterValidation:
    def test_eq_no_value_ok(self):
        tf = TagFilter(key="category")
        assert tf.op == "eq"
        assert tf.value is None

    def test_eq_with_value_ok(self):
        tf = TagFilter(key="category", value="science")
        assert tf.value == "science"

    def test_exists_ok(self):
        tf = TagFilter(key="source", op="exists")
        assert tf.op == "exists"

    def test_prefix_requires_value(self):
        with pytest.raises(ValidationError, match="requires a value"):
            TagFilter(key="topic", op="prefix")

    def test_prefix_with_value_ok(self):
        tf = TagFilter(key="topic", value="ai", op="prefix")
        assert tf.value == "ai"

    def test_numeric_ops_require_value(self):
        for op in ("gt", "gte", "lt", "lte"):
            with pytest.raises(ValidationError, match="requires a numeric value"):
                TagFilter(key="score", op=op)

    def test_numeric_ops_require_numeric_string(self):
        for op in ("gt", "gte", "lt", "lte"):
            with pytest.raises(ValidationError, match="numeric value"):
                TagFilter(key="score", value="not-a-number", op=op)

    def test_numeric_ops_with_valid_value(self):
        tf = TagFilter(key="score", value="0.8", op="gte")
        assert tf.op == "gte"
        assert tf.value == "0.8"

    def test_ne_ok(self):
        tf = TagFilter(key="category", value="spam", op="ne")
        assert tf.op == "ne"


# ── build_tag_filter_sql ──────────────────────────────────────────────────────


class TestBuildTagFilterSql:
    def test_empty_filters(self):
        sql, params = build_tag_filter_sql([])
        assert sql == ""
        assert params == {}

    def test_eq_with_value(self):
        sql, params = build_tag_filter_sql([TagFilter(key="category", value="science")])
        assert "EXISTS" in sql
        assert "= :_tf0v" in sql
        assert params["_tf0v"] == "category:science"

    def test_eq_without_value(self):
        sql, params = build_tag_filter_sql([TagFilter(key="category")])
        assert "EXISTS" in sql
        assert "_tf0p" in sql  # key prefix param used

    def test_ne_with_value(self):
        sql, params = build_tag_filter_sql([TagFilter(key="category", value="spam", op="ne")])
        assert "NOT" in sql
        assert params["_tf0v"] == "category:spam"

    def test_exists_op(self):
        sql, params = build_tag_filter_sql([TagFilter(key="source", op="exists")])
        assert "EXISTS" in sql
        assert "LIKE" in sql
        assert params["_tf0p"] == "source:"

    def test_prefix_op(self):
        sql, params = build_tag_filter_sql([TagFilter(key="topic", value="ai", op="prefix")])
        assert "LIKE" in sql
        assert params["_tf0v"] == "topic:ai"

    def test_gt_op(self):
        sql, params = build_tag_filter_sql([TagFilter(key="score", value="0.8", op="gt")])
        assert "> :_tf0n" in sql
        assert params["_tf0n"] == 0.8
        assert params["_tf0p"] == "score:"

    def test_lte_op(self):
        sql, params = build_tag_filter_sql([TagFilter(key="priority", value="5", op="lte")])
        assert "<= :_tf0n" in sql
        assert params["_tf0n"] == 5.0

    def test_multiple_filters_joined_with_and(self):
        filters = [
            TagFilter(key="category", value="science"),
            TagFilter(key="score", value="0.5", op="gte"),
        ]
        sql, params = build_tag_filter_sql(filters)
        assert "AND" in sql
        assert "_tf0v" in params
        assert "_tf1n" in params

    def test_custom_alias(self):
        sql, _ = build_tag_filter_sql([TagFilter(key="cat", value="x")], alias="ep")
        assert "unnest(ep.tags)" in sql


# ── _matches_tag_filters (Python-side filtering) ──────────────────────────────


class TestMatchesTagFilters:
    """Tests for the Python-side tag filter evaluation used in filter_only mode."""

    from app.api.v1.memory import _matches_tag_filters  # imported lazily below

    def _match(self, tags: list[str], filters: list[TagFilter]) -> bool:
        from app.api.v1.memory import _matches_tag_filters

        return _matches_tag_filters(tags, filters)

    def test_eq_match(self):
        assert self._match(
            ["category:science", "source:web"], [TagFilter(key="category", value="science")]
        )

    def test_eq_no_match(self):
        assert not self._match(["category:arts"], [TagFilter(key="category", value="science")])

    def test_eq_no_value_match(self):
        assert self._match(["category:anything"], [TagFilter(key="category")])

    def test_eq_no_value_no_match(self):
        assert not self._match(["source:web"], [TagFilter(key="category")])

    def test_ne_excludes_match(self):
        assert not self._match(
            ["category:spam"], [TagFilter(key="category", value="spam", op="ne")]
        )

    def test_ne_passes_when_absent(self):
        assert self._match(["category:science"], [TagFilter(key="category", value="spam", op="ne")])

    def test_exists_match(self):
        assert self._match(["source:web"], [TagFilter(key="source", op="exists")])

    def test_exists_no_match(self):
        assert not self._match(["category:x"], [TagFilter(key="source", op="exists")])

    def test_prefix_match(self):
        assert self._match(["topic:ai-safety"], [TagFilter(key="topic", value="ai", op="prefix")])

    def test_prefix_no_match(self):
        assert not self._match(["topic:biology"], [TagFilter(key="topic", value="ai", op="prefix")])

    def test_gt_match(self):
        assert self._match(["score:0.9"], [TagFilter(key="score", value="0.8", op="gt")])

    def test_gt_no_match(self):
        assert not self._match(["score:0.7"], [TagFilter(key="score", value="0.8", op="gt")])

    def test_gte_boundary(self):
        assert self._match(["score:0.8"], [TagFilter(key="score", value="0.8", op="gte")])

    def test_lt_match(self):
        assert self._match(["priority:3"], [TagFilter(key="priority", value="5", op="lt")])

    def test_lte_boundary(self):
        assert self._match(["priority:5"], [TagFilter(key="priority", value="5", op="lte")])

    def test_numeric_non_numeric_tag_ignored(self):
        # non-numeric value for numeric key is skipped — no match found
        assert not self._match(["score:high"], [TagFilter(key="score", value="0.8", op="gt")])

    def test_multiple_filters_all_must_pass(self):
        tags = ["category:science", "score:0.9", "source:web"]
        filters = [
            TagFilter(key="category", value="science"),
            TagFilter(key="score", value="0.8", op="gte"),
            TagFilter(key="source", op="exists"),
        ]
        assert self._match(tags, filters)

    def test_multiple_filters_one_fails(self):
        tags = ["category:science", "score:0.5"]
        filters = [
            TagFilter(key="category", value="science"),
            TagFilter(key="score", value="0.8", op="gte"),
        ]
        assert not self._match(tags, filters)

    def test_mixed_flat_and_structured(self):
        # flat tag "featured" alongside structured "category:science"
        tags = ["featured", "category:science"]
        assert self._match(tags, [TagFilter(key="category", value="science")])


# ── API-level validation (bad numeric value → 422) ────────────────────────────


@pytest.mark.asyncio
@pytest.mark.integration
async def test_tag_filter_bad_numeric_returns_422(client):
    """Sending op='gt' with a non-numeric value should produce a 422."""
    import uuid as _uuid

    # Register a real user so auth passes and we reach body validation
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "email": f"tagfilter-{_uuid.uuid4().hex[:8]}@example.com",
            "password": "password123",
            "org_name": "Tag Filter Test Org",
        },
    )
    token = reg.json()["data"]["access_token"]

    resp = await client.post(
        "/api/v1/memory/search",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "query": "test",
            "tag_filters": [{"key": "score", "value": "not-a-number", "op": "gt"}],
        },
    )
    assert resp.status_code == 422
