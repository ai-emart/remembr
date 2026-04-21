"""Remembr CLI — `remembr` command entry point."""

from __future__ import annotations

import asyncio
import json
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from remembr import RemembrClient
from remembr.exceptions import RemembrError

from . import config as cfg
from .output import (
    console,
    episodes_table,
    err_console,
    print_error,
    print_json,
    print_success,
    sessions_table,
)

# ── Typer app tree ─────────────────────────────────────────────────────────────

app = typer.Typer(
    name="remembr",
    help="Remembr — persistent memory for AI agents.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

config_app = typer.Typer(help="Manage CLI configuration.", no_args_is_help=True)
sessions_app = typer.Typer(help="Session management.", no_args_is_help=True)
app.add_typer(config_app, name="config")
app.add_typer(sessions_app, name="sessions")

# Module-level state set by the root callback so every sub-command can read it.
_state: dict = {"verbose": False, "api_key": None, "base_url": None}


# ── Root callback (version + global flags) ─────────────────────────────────────

def _version_callback(value: bool) -> None:
    if value:
        from importlib.metadata import PackageNotFoundError, version
        try:
            v = version("remembr")
        except PackageNotFoundError:
            v = "unknown"
        typer.echo(f"remembr {v}")
        raise typer.Exit()


@app.callback()
def root(
    version: Annotated[
        Optional[bool],
        typer.Option("--version", "-V", callback=_version_callback, is_eager=True, help="Show version."),
    ] = None,
    api_key: Annotated[
        Optional[str],
        typer.Option("--api-key", envvar="REMEMBR_API_KEY", help="Override API key.", show_default=False),
    ] = None,
    base_url: Annotated[
        Optional[str],
        typer.Option("--base-url", envvar="REMEMBR_BASE_URL", help="Override base URL.", show_default=False),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Show full stack traces on errors."),
    ] = False,
) -> None:
    """Remembr — persistent memory for AI agents."""
    _state["verbose"] = verbose
    # Explicit flag > env var (already resolved by envvar=) > config file > default
    file_api_key, file_base_url = cfg.resolve_client_args()
    _state["api_key"] = api_key or file_api_key
    _state["base_url"] = base_url or file_base_url


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_client() -> RemembrClient:
    api_key = _state["api_key"]
    base_url = _state["base_url"] or "http://localhost:8000/api/v1"
    if not api_key:
        print_error(
            "No API key found. Set it with:\n"
            "  remembr config set api_key <your-key>\n"
            "or pass --api-key / export REMEMBR_API_KEY=<your-key>"
        )
        raise typer.Exit(1)
    return RemembrClient(api_key=api_key, base_url=base_url)


def _run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


@contextmanager
def _catch():
    """Context manager: pretty-print RemembrError; show traceback only if --verbose."""
    try:
        yield
    except RemembrError as exc:
        if _state["verbose"]:
            err_console.print_exception()
        else:
            msg = str(exc)
            if exc.code:
                msg = f"[{exc.code}] {msg}"
            if exc.status_code:
                msg = f"HTTP {exc.status_code}: {msg}"
            print_error(msg)
        raise typer.Exit(1)
    except Exception as exc:  # unexpected
        if _state["verbose"]:
            err_console.print_exception()
        else:
            print_error(f"Unexpected error: {exc}")
        raise typer.Exit(1)


def _parse_date(value: str | None, flag: str) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        print_error(f"{flag} must be YYYY-MM-DD, got '{value}'")
        raise typer.Exit(1)


# ── config ────────────────────────────────────────────────────────────────────

@config_app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help="Config key (api_key or base_url).")],
    value: Annotated[str, typer.Argument(help="Value to set.")],
) -> None:
    """Set a config value in ~/.remembr/config.toml."""
    try:
        cfg.set_value(key, value)
        print_success(f"Set [bold]{key}[/bold] in ~/.remembr/config.toml")
    except ValueError as exc:
        print_error(str(exc))
        raise typer.Exit(1)


@config_app.command("get")
def config_get(
    key: Annotated[str, typer.Argument(help="Config key to retrieve.")],
) -> None:
    """Print a single config value."""
    value = cfg.get(key)
    if value is None:
        print_error(f"Key '{key}' not set.")
        raise typer.Exit(1)
    typer.echo(value)


@config_app.command("show")
def config_show() -> None:
    """Show all config values."""
    values = cfg.all_values()
    if not values:
        console.print(
            "[dim]No configuration found. "
            "Use [bold]remembr config set[/bold] to get started.[/dim]"
        )
        return
    for k, v in values.items():
        display = f"{v[:6]}..." if k == "api_key" and len(str(v)) > 6 else v
        console.print(f"[bold cyan]{k}[/bold cyan] = {display}")


# ── health ────────────────────────────────────────────────────────────────────

@app.command()
def health() -> None:
    """Check service health."""
    import httpx

    base_url = _state["base_url"] or "http://localhost:8000/api/v1"
    health_url = base_url.rstrip("/").removesuffix("/api/v1") + "/health"

    with _catch():
        try:
            response = httpx.get(health_url, timeout=10)
            response.raise_for_status()
        except httpx.ConnectError:
            print_error(f"Connection refused: {health_url}")
            raise typer.Exit(1)
        except httpx.HTTPStatusError as exc:
            print_error(f"HTTP {exc.response.status_code} from {health_url}")
            raise typer.Exit(1)

        data = response.json()
        status = data.get("status", "unknown")
        color = "green" if status == "ok" else "red"
        console.print(f"[bold {color}]*[/bold {color}] status: [bold]{status}[/bold]")
        for k, v in data.items():
            if k != "status":
                console.print(f"  {k}: {v}")


# ── store ─────────────────────────────────────────────────────────────────────

@app.command()
def store(
    content: Annotated[str, typer.Argument(help="Memory content to store.")],
    session: Annotated[Optional[str], typer.Option("--session", "-s", help="Session ID.")] = None,
    role: Annotated[str, typer.Option("--role", "-r", help="Role label.")] = "user",
    tags: Annotated[Optional[str], typer.Option("--tags", "-t", help="Comma-separated tags.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON.")] = False,
) -> None:
    """Store a memory episode."""
    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    async def _store() -> None:
        with _catch():
            async with _make_client() as client:
                episode = await client.store(
                    content, role=role, session_id=session, tags=tag_list
                )

        if as_json:
            print_json(episode.model_dump())
        else:
            print_success(f"Stored episode [bold cyan]{episode.episode_id}[/bold cyan]")
            console.print(f"  role   : {episode.role}")
            console.print(f"  session: {episode.session_id or '-'}")
            console.print(f"  tags   : {', '.join(episode.tags) or '-'}")
            console.print(f"  created: {episode.created_at}")

    _run(_store())


# ── search ────────────────────────────────────────────────────────────────────

@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query.")],
    session: Annotated[Optional[str], typer.Option("--session", "-s", help="Scope to session.")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max results.")] = 10,
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON.")] = False,
) -> None:
    """Search memory episodes."""

    async def _search() -> None:
        with _catch():
            async with _make_client() as client:
                result = await client.search(query, session_id=session, limit=limit)

        if as_json:
            print_json([r.model_dump() for r in result.results])
        else:
            console.print(f"[dim]{result.total} total · {result.query_time_ms} ms[/dim]")
            if not result.results:
                console.print("[dim]No results found.[/dim]")
                return
            console.print(episodes_table([r.model_dump() for r in result.results], title=f'Search: "{query}"'))

    _run(_search())


# ── sessions list ─────────────────────────────────────────────────────────────

@sessions_app.command("list")
def sessions_list(
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max results.")] = 20,
    offset: Annotated[int, typer.Option("--offset", help="Skip N sessions.")] = 0,
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON.")] = False,
) -> None:
    """List sessions."""

    async def _list() -> None:
        with _catch():
            async with _make_client() as client:
                sessions = await client.list_sessions(limit=limit, offset=offset)

        if as_json:
            print_json([s.model_dump() for s in sessions])
        else:
            console.print(sessions_table([s.model_dump() for s in sessions]))

    _run(_list())


# ── sessions get ──────────────────────────────────────────────────────────────

@sessions_app.command("get")
def sessions_get(
    session_id: Annotated[str, typer.Argument(help="Session ID.")],
    as_json: Annotated[bool, typer.Option("--json", help="Output raw JSON.")] = False,
) -> None:
    """Get session details, window messages, and token usage."""

    async def _get() -> None:
        import httpx as _httpx

        api_key = _state["api_key"]
        base_url = _state["base_url"] or "http://localhost:8000/api/v1"
        if not api_key:
            print_error("No API key configured.")
            raise typer.Exit(1)

        with _catch():
            async with _httpx.AsyncClient(
                base_url=base_url,
                headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
                timeout=30,
            ) as http:
                resp = await http.get(f"/sessions/{session_id}")
                if resp.status_code == 404:
                    print_error(f"Session '{session_id}' not found.")
                    raise typer.Exit(1)
                resp.raise_for_status()
                data = resp.json().get("data", resp.json())

        if as_json:
            print_json(data)
            return

        session = data.get("session", {})
        console.print(f"\n[bold cyan]Session[/bold cyan] {session.get('session_id', session_id)}")
        console.print(f"  org_id  : {session.get('org_id', '-')}")
        console.print(f"  created : {session.get('created_at', '-')}")
        meta = session.get("metadata") or {}
        if meta:
            console.print(f"  metadata: {json.dumps(meta)}")

        messages = data.get("messages", [])
        if messages:
            console.print(f"\n[bold]Window[/bold] ({len(messages)} message(s)):")
            for msg in messages:
                role_color = "blue" if msg.get("role") == "assistant" else "green"
                console.print(
                    f"  [{role_color}]{msg.get('role', '?')}[/{role_color}]: "
                    f"{msg.get('content', '')[:120]}"
                )

        token_usage = data.get("token_usage", {})
        if token_usage:
            console.print(f"\n[bold]Token usage[/bold]: {json.dumps(token_usage)}")

    _run(_get())


# ── export ────────────────────────────────────────────────────────────────────

@app.command()
def export(
    output: Annotated[
        Optional[Path], typer.Option("--output", "-o", help="Output file path.")
    ] = None,
    format: Annotated[str, typer.Option("--format", "-f", help="json or csv.")] = "json",
    from_date: Annotated[
        Optional[str], typer.Option("--from", help="From date (YYYY-MM-DD).")
    ] = None,
    to_date: Annotated[
        Optional[str], typer.Option("--to", help="To date (YYYY-MM-DD).")
    ] = None,
    session: Annotated[
        Optional[str], typer.Option("--session", "-s", help="Session ID.")
    ] = None,
) -> None:
    """Export memories to a file (JSON or CSV) with progress."""
    if format not in ("json", "csv"):
        print_error("--format must be 'json' or 'csv'")
        raise typer.Exit(1)

    from_dt = _parse_date(from_date, "--from")
    to_dt = _parse_date(to_date, "--to")
    dest = output or Path(f"remembr_export.{format}")

    async def _export() -> None:
        with _catch():
            async with _make_client() as client:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    BarColumn(),
                    TextColumn("{task.completed} episodes"),
                    TimeElapsedColumn(),
                    console=console,
                    transient=True,
                ) as progress:
                    task = progress.add_task(f"Exporting to {dest.name}...", total=None)

                    stream = await client.export(
                        format=format,
                        from_date=from_dt,
                        to_date=to_dt,
                        session_id=session,
                    )

                    if format == "csv":
                        assert isinstance(stream, bytes)
                        dest.write_bytes(stream)
                        progress.update(task, completed=1, total=1)
                    else:
                        count = 0
                        first = True
                        with dest.open("w", encoding="utf-8") as fh:
                            fh.write("[\n")
                            async for episode in stream:  # type: ignore[union-attr]
                                if not first:
                                    fh.write(",\n")
                                fh.write(json.dumps(episode))
                                first = False
                                count += 1
                                progress.update(task, completed=count)
                            fh.write("\n]\n")

        print_success(f"Exported to [bold]{dest}[/bold]")

    _run(_export())
