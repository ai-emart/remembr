"""Tests for `remembr export`."""

from __future__ import annotations

import json

import httpx
import respx

from remembr.cli.main import app

_EXPORT_URL = "http://test.local/api/v1/export"


def _json_body(episodes: list) -> bytes:
    return json.dumps(episodes).encode()


@respx.mock
def test_export_json_writes_file(runner, tmp_path, sample_episode):
    dest = tmp_path / "out.json"
    body = _json_body([sample_episode])
    respx.route(url__startswith=_EXPORT_URL).mock(
        return_value=httpx.Response(
            200, content=body, headers={"Content-Type": "application/json"}
        )
    )
    result = runner.invoke(app, ["export", "--output", str(dest), "--format", "json"])
    assert result.exit_code == 0, result.output
    assert dest.exists()
    parsed = json.loads(dest.read_text())
    assert parsed[0]["episode_id"] == "ep_abc"


@respx.mock
def test_export_csv_writes_file(runner, tmp_path):
    dest = tmp_path / "out.csv"
    csv_body = b"id,session_id,role,content,tags,metadata,created_at,embedding_status\n"
    respx.route(url__startswith=_EXPORT_URL).mock(
        return_value=httpx.Response(
            200, content=csv_body, headers={"Content-Type": "text/csv"}
        )
    )
    result = runner.invoke(app, ["export", "--output", str(dest), "--format", "csv"])
    assert result.exit_code == 0, result.output
    assert dest.exists()
    assert b"role" in dest.read_bytes()


def test_export_invalid_format(runner):
    result = runner.invoke(app, ["export", "--format", "xml"])
    assert result.exit_code != 0
    assert "Error" in result.output or "must be" in result.output


def test_export_invalid_date(runner):
    result = runner.invoke(app, ["export", "--from", "not-a-date"])
    assert result.exit_code != 0
    assert "YYYY-MM-DD" in result.output or "Error" in result.output


@respx.mock
def test_export_auth_error(runner, tmp_path):
    dest = tmp_path / "out.json"
    respx.route(url__startswith=_EXPORT_URL).mock(
        return_value=httpx.Response(
            401, json={"error": {"message": "Unauthorized", "code": "INVALID_TOKEN"}}
        )
    )
    result = runner.invoke(app, ["export", "--output", str(dest)])
    assert result.exit_code != 0
    assert "Error" in result.output or "401" in result.output


@respx.mock
def test_export_default_filename(runner, tmp_path, sample_episode, monkeypatch):
    monkeypatch.chdir(tmp_path)
    body = _json_body([sample_episode])
    respx.route(url__startswith=_EXPORT_URL).mock(
        return_value=httpx.Response(
            200, content=body, headers={"Content-Type": "application/json"}
        )
    )
    result = runner.invoke(app, ["export"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "remembr_export.json").exists()
