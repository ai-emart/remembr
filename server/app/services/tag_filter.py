"""Structured tag filter model and SQL predicate builder."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class TagFilter(BaseModel):
    """Filter on a structured ``key:value`` tag.

    Flat string tags (no colon) are matched only by the ``eq`` and ``ne`` ops —
    they behave identically to ``key:value`` tags where ``key`` is the full string
    and ``value`` is ``None`` / absent.
    """

    key: str = Field(..., min_length=1)
    value: str | None = None
    op: Literal["eq", "ne", "gt", "gte", "lt", "lte", "exists", "prefix"] = "eq"

    @model_validator(mode="after")
    def _validate_numeric_ops(self) -> TagFilter:
        if self.op in ("gt", "gte", "lt", "lte"):
            if self.value is None:
                raise ValueError(f"op={self.op!r} requires a numeric value (key={self.key!r})")
            try:
                float(self.value)
            except ValueError:
                raise ValueError(
                    f"op={self.op!r} requires a numeric value;"
                    f" got {self.value!r} for key={self.key!r}"
                )
        if self.op == "prefix" and self.value is None:
            raise ValueError(f"op='prefix' requires a value (key={self.key!r})")
        return self


def build_tag_filter_sql(
    filters: list[TagFilter],
    *,
    alias: str = "e",
) -> tuple[str, dict]:
    """Translate a list of TagFilters into a parameterized SQL AND-predicate.

    Returns ``(sql_snippet, params)`` where ``sql_snippet`` is a whitespace-joined
    series of ``AND <condition>`` clauses safe to embed directly inside an existing
    WHERE block.  All user-supplied strings land in ``params`` — no string
    interpolation of user data into the SQL template.

    Usage::

        snippet, extra_params = build_tag_filter_sql(filters, alias="e")
        full_sql = base_sql + (f"\\n  AND {snippet}" if snippet else "")
        params = {**base_params, **extra_params}
    """
    if not filters:
        return "", {}

    parts: list[str] = []
    params: dict[str, object] = {}

    for i, tf in enumerate(filters):
        prefix_param = f"_tf{i}p"  # 'key:' string for LIKE prefix match
        pattern_param = f"_tf{i}r"  # '^key:(.+)$' regexp for numeric extraction
        exact_param = f"_tf{i}v"  # exact 'key:value' string
        num_param = f"_tf{i}n"  # numeric value for gt/gte/lt/lte

        key_prefix = f"{tf.key}:"

        if tf.op == "exists":
            params[prefix_param] = key_prefix
            parts.append(
                f"EXISTS (SELECT 1 FROM unnest({alias}.tags) AS _t"
                f" WHERE _t LIKE :{prefix_param} || '%')"
            )

        elif tf.op in ("eq", "ne"):
            if tf.value is None:
                # Treat as flat-string or key-exists match
                params[prefix_param] = key_prefix
                exists = (
                    f"EXISTS (SELECT 1 FROM unnest({alias}.tags) AS _t"
                    f" WHERE _t LIKE :{prefix_param} || '%'"
                    f" OR _t = :{prefix_param})"  # also handle plain 'key:' tag
                )
                parts.append(exists if tf.op == "eq" else f"NOT ({exists})")
            else:
                params[exact_param] = f"{tf.key}:{tf.value}"
                exists = (
                    f"EXISTS (SELECT 1 FROM unnest({alias}.tags) AS _t WHERE _t = :{exact_param})"
                )
                parts.append(exists if tf.op == "eq" else f"NOT ({exists})")

        elif tf.op == "prefix":
            # tf.value is guaranteed non-None by the model validator
            params[exact_param] = f"{tf.key}:{tf.value}"
            parts.append(
                f"EXISTS (SELECT 1 FROM unnest({alias}.tags) AS _t"
                f" WHERE _t LIKE :{exact_param} || '%')"
            )

        else:
            # gt / gte / lt / lte — numeric comparison
            params[pattern_param] = f"^{tf.key}:(.+)$"
            params[prefix_param] = key_prefix
            params[num_param] = float(tf.value)  # type: ignore[arg-type]
            op_sql = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[tf.op]
            parts.append(
                f"EXISTS (SELECT 1 FROM unnest({alias}.tags) AS _t"
                f" WHERE _t LIKE :{prefix_param} || '%'"
                f" AND (regexp_match(_t, :{pattern_param}))[1]::numeric {op_sql} :{num_param})"
            )

    return "\n              AND ".join(parts), params
