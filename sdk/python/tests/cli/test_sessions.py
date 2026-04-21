"""Tests for `remembr sessions list` and `remembr sessions get`."""

from __future__ import annotations

import json

import httpx
import respx

from remembr.cli.main import app


@respx.mock
def test_sessions_list_table(runner, sample_session):
    respx.get("http://test.local/api/v1/sessions").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "request_id": "req_abc",
                    "sessions": [sample_session],
                    "total": 1,
                    "limit": 20,
                    "offset": 0,
                }
            },
        )
    )
    result = runner.invoke(app, ["sessions", "list"])
    assert result.exit_code == 0
    assert "sess_abc" in result.output


@respx.mock
def test_sessions_list_json(runner, sample_session):
    respx.get("http://test.local/api/v1/sessions").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "request_id": "req_abc",
                    "sessions": [sample_session],
                    "total": 1,
                    "limit": 20,
                    "offset": 0,
                }
            },
        )
    )
    result = runner.invoke(app, ["sessions", "list", "--json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert parsed[0]["session_id"] == "sess_abc"


@respx.mock
def test_sessions_list_auth_error(runner):
    respx.get("http://test.local/api/v1/sessions").mock(
        return_value=httpx.Response(
            401, json={"error": {"message": "Unauthorized", "code": "INVALID_TOKEN"}}
        )
    )
    result = runner.invoke(app, ["sessions", "list"])
    assert result.exit_code != 0
    assert "Error" in result.output or "401" in result.output


@respx.mock
def test_sessions_get_happy_path(runner, sample_session):
    detail = {
        "session": sample_session,
        "messages": [{"role": "user", "content": "hi there"}],
        "token_usage": {"total": 10},
    }
    respx.get("http://test.local/api/v1/sessions/sess_abc").mock(
        return_value=httpx.Response(200, json={"data": detail})
    )
    result = runner.invoke(app, ["sessions", "get", "sess_abc"])
    assert result.exit_code == 0
    assert "sess_abc" in result.output
    assert "hi there" in result.output
    assert "token_usage" in result.output or "Token usage" in result.output


@respx.mock
def test_sessions_get_json(runner, sample_session):
    detail = {"session": sample_session, "messages": [], "token_usage": {}}
    respx.get("http://test.local/api/v1/sessions/sess_abc").mock(
        return_value=httpx.Response(200, json={"data": detail})
    )
    result = runner.invoke(app, ["sessions", "get", "sess_abc", "--json"])
    assert result.exit_code == 0
    parsed = json.loads(result.output)
    assert "session" in parsed


@respx.mock
def test_sessions_get_not_found(runner):
    respx.get("http://test.local/api/v1/sessions/missing").mock(
        return_value=httpx.Response(
            404, json={"error": {"message": "Not found", "code": "SESSION_NOT_FOUND"}}
        )
    )
    result = runner.invoke(app, ["sessions", "get", "missing"])
    assert result.exit_code != 0
    assert "not found" in result.output.lower() or "Error" in result.output
