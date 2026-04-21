"""Shared fixtures for CLI tests."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from remembr.cli.main import _state

TEST_API_KEY = "test-key"
TEST_BASE_URL = "http://test.local/api/v1"


@pytest.fixture(autouse=True)
def patch_config(monkeypatch):
    """Ensure every test runs with known API key + base URL, regardless of ~/.remembr/config.toml."""
    monkeypatch.setattr(
        "remembr.cli.config.resolve_client_args",
        lambda: (TEST_API_KEY, TEST_BASE_URL),
    )
    # Pre-seed state for commands that read it directly (sessions get, health)
    _state.update({"verbose": False, "api_key": TEST_API_KEY, "base_url": TEST_BASE_URL})
    yield
    _state.update({"verbose": False, "api_key": None, "base_url": None})


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_episode():
    return {
        "episode_id": "ep_abc",
        "session_id": "sess_abc",
        "role": "user",
        "content": "hello world",
        "created_at": "2026-01-01T00:00:00Z",
        "tags": ["test"],
        "metadata": {},
    }


@pytest.fixture
def sample_session():
    return {
        "request_id": "req_abc",
        "session_id": "sess_abc",
        "org_id": "org_abc",
        "created_at": "2026-01-01T00:00:00Z",
        "metadata": {},
    }


@pytest.fixture
def sample_search_result():
    return {
        "episode_id": "ep_abc",
        "content": "hello world",
        "role": "user",
        "score": 0.95,
        "created_at": "2026-01-01T00:00:00Z",
        "tags": ["test"],
    }
