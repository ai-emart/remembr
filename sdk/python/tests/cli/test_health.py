"""Tests for `remembr health`."""

from __future__ import annotations

import httpx
import respx

from remembr.cli.main import app

_HEALTH_URL = "http://test.local/api/v1/health"


@respx.mock
def test_health_ok(runner):
    respx.get(_HEALTH_URL).mock(
        return_value=httpx.Response(
            200, json={"status": "ok", "version": "0.2.0", "environment": "local"}
        )
    )
    result = runner.invoke(app, ["health"])
    assert result.exit_code == 0, result.output
    assert "ok" in result.output
    assert "version" in result.output


@respx.mock
def test_health_degraded(runner):
    respx.get(_HEALTH_URL).mock(
        return_value=httpx.Response(200, json={"status": "degraded"})
    )
    result = runner.invoke(app, ["health"])
    assert result.exit_code == 0, result.output
    assert "degraded" in result.output


@respx.mock
def test_health_connection_refused(runner):
    respx.get(_HEALTH_URL).mock(side_effect=httpx.ConnectError("refused"))
    result = runner.invoke(app, ["health"])
    assert result.exit_code != 0
    assert "refused" in result.output.lower() or "Error" in result.output
