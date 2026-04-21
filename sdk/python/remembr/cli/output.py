"""Rich-based output helpers for the remembr CLI."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from rich import print as rprint
from rich.console import Console
from rich.table import Table

console = Console()
err_console = Console(stderr=True)


def print_error(message: str) -> None:
    err_console.print(f"[bold red]Error:[/bold red] {message}")


def print_success(message: str) -> None:
    console.print(f"[bold green]OK[/bold green] {message}")


def print_json(data: Any) -> None:
    console.print_json(json.dumps(data, default=_default))


def _default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def episodes_table(episodes: list[dict[str, Any]], title: str = "Results") -> Table:
    table = Table(title=title, show_lines=True)
    table.add_column("Episode ID", style="cyan", no_wrap=True, max_width=36)
    table.add_column("Role", style="magenta", width=10)
    table.add_column("Content", style="white", max_width=60)
    table.add_column("Score", justify="right", width=7)
    table.add_column("Tags", style="yellow")
    table.add_column("Created", style="dim", no_wrap=True)

    for ep in episodes:
        score = ep.get("score")
        table.add_row(
            str(ep.get("episode_id", "")),
            str(ep.get("role", "")),
            str(ep.get("content", "")),
            f"{score:.3f}" if score is not None else "—",
            ", ".join(ep.get("tags") or []),
            _fmt_dt(ep.get("created_at")),
        )
    return table


def sessions_table(sessions: list[dict[str, Any]]) -> Table:
    table = Table(title="Sessions", show_lines=False)
    table.add_column("Session ID", style="cyan", no_wrap=True, max_width=36)
    table.add_column("Created", style="dim", no_wrap=True)
    table.add_column("Messages", justify="right", width=9)
    table.add_column("Metadata", style="yellow", max_width=40)

    for s in sessions:
        meta = s.get("metadata") or {}
        table.add_row(
            str(s.get("session_id", "")),
            _fmt_dt(s.get("created_at")),
            str(s.get("message_count", "—")),
            json.dumps(meta) if meta else "—",
        )
    return table


def _fmt_dt(value: Any) -> str:
    if not value:
        return "—"
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            dt = value
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return str(value)
