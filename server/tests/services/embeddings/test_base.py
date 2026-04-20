"""Tests confirming EmbeddingProvider ABC cannot be instantiated directly."""

from __future__ import annotations

import pytest

from app.services.embeddings.base import EmbeddingProvider


def test_cannot_instantiate_abc():
    with pytest.raises(TypeError):
        EmbeddingProvider()  # type: ignore[abstract]


def test_concrete_subclass_must_implement_all_methods():
    class Incomplete(EmbeddingProvider):
        @property
        def model(self):
            return "x"

    with pytest.raises(TypeError):
        Incomplete()  # type: ignore[abstract]
