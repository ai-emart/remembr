"""Tests for `remembr search`."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from remembr.cli.main import app


def _search_response(results):
    return httpx.Response(
        200,
        json={
            "data": {
                "request_id": "req_xyz",
                "results": results,
                "total": len(results),
                "query_time_ms": 8,
            }
        },
    )


@respx.mock
def test_search_happy_path_table(runner, sample_search_result):
    respx.post("http://test.local/api/v1/memory/search").mock(
        return_value=_search_response([sample_search_result])
    )
    result = runner.invoke(app, ["search", "hello"])
    assert result.exit_code == 0, result.output
    assert "ep_abc" in result.output


@respx.mock
def test_search_json_output(runner, sample_search_result):
    respx.post("http://test.local/api/v1/memory/search").mock(
        return_value=_search_response([sample_search_result])
    )
    result = runner.invoke(app, ["search", "hello", "--json"])
    assert result.exit_code == 0, result.output
    parsed = json.loads(result.output)
    assert parsed[0]["episode_id"] == "ep_abc"
    assert parsed[0]["score"] == pytest.approx(0.95)


@respx.mock
def test_search_no_results(runner):
    respx.post("http://test.local/api/v1/memory/search").mock(
        return_value=_search_response([])
    )
    result = runner.invoke(app, ["search", "nothing"])
    assert result.exit_code == 0, result.output
    assert "No results" in result.output


@respx.mock
def test_search_with_session_and_limit(runner, sample_search_result):
    respx.post("http://test.local/api/v1/memory/search").mock(
        return_value=_search_response([sample_search_result])
    )
    result = runner.invoke(
        app, ["search", "hello", "--session", "sess_abc", "--limit", "5"]
    )
    assert result.exit_code == 0, result.output


@respx.mock
def test_search_auth_error(runner):
    respx.post("http://test.local/api/v1/memory/search").mock(
        return_value=httpx.Response(
            401, json={"error": {"message": "Unauthorized", "code": "INVALID_TOKEN"}}
        )
    )
    result = runner.invoke(app, ["search", "query"])
    assert result.exit_code != 0
    assert "Error" in result.output or "401" in result.output
