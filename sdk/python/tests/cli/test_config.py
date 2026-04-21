"""Tests for `remembr config` subcommands."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from remembr.cli.main import app


def test_config_set_and_get(runner, tmp_path, monkeypatch):
    monkeypatch.setattr("remembr.cli.config._CONFIG_DIR", tmp_path / ".remembr")
    monkeypatch.setattr("remembr.cli.config._CONFIG_FILE", tmp_path / ".remembr" / "config.toml")

    result = runner.invoke(app, ["config", "set", "api_key", "my-secret-key"])
    assert result.exit_code == 0
    assert "api_key" in result.output

    result = runner.invoke(app, ["config", "get", "api_key"])
    assert result.exit_code == 0
    assert "my-secret-key" in result.output


def test_config_set_base_url(runner, tmp_path, monkeypatch):
    monkeypatch.setattr("remembr.cli.config._CONFIG_DIR", tmp_path / ".remembr")
    monkeypatch.setattr("remembr.cli.config._CONFIG_FILE", tmp_path / ".remembr" / "config.toml")

    result = runner.invoke(app, ["config", "set", "base_url", "https://my.server/api/v1"])
    assert result.exit_code == 0

    result = runner.invoke(app, ["config", "get", "base_url"])
    assert result.exit_code == 0
    assert "https://my.server/api/v1" in result.output


def test_config_set_invalid_key(runner, tmp_path, monkeypatch):
    monkeypatch.setattr("remembr.cli.config._CONFIG_DIR", tmp_path / ".remembr")
    monkeypatch.setattr("remembr.cli.config._CONFIG_FILE", tmp_path / ".remembr" / "config.toml")

    result = runner.invoke(app, ["config", "set", "unknown_key", "value"])
    assert result.exit_code != 0
    assert "Unknown config key" in result.output or "Unknown config key" in (result.stderr or "")


def test_config_get_missing_key(runner, tmp_path, monkeypatch):
    monkeypatch.setattr("remembr.cli.config._CONFIG_DIR", tmp_path / ".remembr")
    monkeypatch.setattr("remembr.cli.config._CONFIG_FILE", tmp_path / ".remembr" / "config.toml")

    result = runner.invoke(app, ["config", "get", "api_key"])
    assert result.exit_code != 0


def test_config_show_empty(runner, tmp_path, monkeypatch):
    monkeypatch.setattr("remembr.cli.config._CONFIG_DIR", tmp_path / ".remembr")
    monkeypatch.setattr("remembr.cli.config._CONFIG_FILE", tmp_path / ".remembr" / "config.toml")

    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "No configuration" in result.output


def test_config_show_masks_api_key(runner, tmp_path, monkeypatch):
    monkeypatch.setattr("remembr.cli.config._CONFIG_DIR", tmp_path / ".remembr")
    monkeypatch.setattr("remembr.cli.config._CONFIG_FILE", tmp_path / ".remembr" / "config.toml")

    runner.invoke(app, ["config", "set", "api_key", "supersecretkey123"])
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "supersecretkey123" not in result.output
    assert "supers" in result.output  # first 6 chars visible
    assert "..." in result.output
