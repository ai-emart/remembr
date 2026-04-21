"""Load and save ~/.remembr/config.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

_CONFIG_DIR = Path.home() / ".remembr"
_CONFIG_FILE = _CONFIG_DIR / "config.toml"

_VALID_KEYS = {"base_url", "api_key"}


def _load_raw() -> dict[str, Any]:
    if not _CONFIG_FILE.exists():
        return {}
    with _CONFIG_FILE.open("rb") as fh:
        return tomllib.load(fh)


def _save_raw(data: dict[str, Any]) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f'{k} = "{v}"' for k, v in data.items()]
    _CONFIG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def get(key: str) -> str | None:
    return _load_raw().get(key)


def set_value(key: str, value: str) -> None:
    if key not in _VALID_KEYS:
        raise ValueError(f"Unknown config key '{key}'. Valid keys: {', '.join(sorted(_VALID_KEYS))}")
    data = _load_raw()
    data[key] = value
    _save_raw(data)


def all_values() -> dict[str, Any]:
    return _load_raw()


def resolve_client_args() -> tuple[str, str]:
    """Return (api_key, base_url) preferring env vars over config file."""
    import os

    cfg = _load_raw()
    api_key = os.getenv("REMEMBR_API_KEY") or cfg.get("api_key") or ""
    base_url = (
        os.getenv("REMEMBR_BASE_URL")
        or cfg.get("base_url")
        or "http://localhost:8000/api/v1"
    )
    return api_key, base_url
