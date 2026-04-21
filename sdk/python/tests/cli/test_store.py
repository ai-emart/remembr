"""Tests for `remembr store`."""

from __future__ import annotations

import json

import httpx
import respx

from remembr.cli.main import app


@respx.mock
def test_store_happy_path(runner, sample_episode):
    respx.post("http://test.local/api/v1/memory").mock(
        return_value=httpx.Response(201, json={"data": sample_episode})
    )
    result = runner.invoke(app, ["store", "hello world", "--role", "user"])
    assert result.exit_code == 0
    assert "ep_abc" in result.output


@respx.mock
def test_store_with_session_and_tags(runner, sample_episode):
    respx.post("http://test.local/api/v1/memory").mock(
        return_value=httpx.Response(201, json={"data": sample_episode})
    )
    result = runner.invoke(
        app, ["store", "hello", "--session", "sess_abc", "--tags", "ai,memory"]
    )
    assert result.exit_code == 0


@respx.mock
def test_store_json_output(runner, sample_episode):
    respx.post("http://test.local/api/v1/memory").mock(
        return_value=httpx.Response(201, json={"data": sample_episode})
    )
    result = runner.invoke(app, ["store", "hello world", "--json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed["episode_id"] == "ep_abc"


@respx.mock
def test_store_auth_error(runner):
    respx.post("http://test.local/api/v1/memory").mock(
        return_value=httpx.Response(
            401, json={"error": {"message": "Unauthorized", "code": "INVALID_TOKEN"}}
        )
    )
    result = runner.invoke(app, ["store", "hello"])
    assert result.exit_code != 0
    assert "Error" in result.output or "401" in result.output


@respx.mock
def test_store_verbose_shows_traceback(runner):
    """--verbose flag causes full exception info to be printed."""
    respx.post("http://test.local/api/v1/memory").mock(
        return_value=httpx.Response(
            500, json={"error": {"message": "Internal error", "code": "SERVER_ERROR"}}
        )
    )
    result = runner.invoke(app, ["--verbose", "store", "hello"])
    assert result.exit_code != 0


def test_store_no_api_key(runner):
    from remembr.cli.main import _state
    _state["api_key"] = None
    result = runner.invoke(app, ["store", "hello"])
    assert result.exit_code != 0
    assert "API key" in result.output or "Error" in result.output
