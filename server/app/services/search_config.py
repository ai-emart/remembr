"""Search configuration models shared across API and services."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

SEARCH_MODE_VALUES = ("semantic", "keyword", "hybrid")
DEFAULT_SEARCH_MODE = "hybrid"
WEIGHT_SUM_ERROR_MESSAGE = "weights.semantic + weights.keyword + weights.recency must sum to 1.0"


class SearchWeights(BaseModel):
    """Weighted coefficients for hybrid search ranking."""

    semantic: float = Field(default=0.6, ge=0.0, le=1.0)
    keyword: float = Field(default=0.3, ge=0.0, le=1.0)
    recency: float = Field(default=0.1, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_total(self) -> SearchWeights:
        total = self.semantic + self.keyword + self.recency
        if abs(total - 1.0) > 1e-9:
            raise ValueError(WEIGHT_SUM_ERROR_MESSAGE)
        return self


SearchMode = Literal["semantic", "keyword", "hybrid"]
