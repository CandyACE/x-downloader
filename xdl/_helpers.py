"""Shared utilities used across CLI command modules."""
from __future__ import annotations

import json
from datetime import date as _date, datetime as _datetime
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .db import KVStore
from .media_parser import MediaItem

console = Console()

# Key format used in the DB/store state table
_CURSOR_KEY = "cursor:{mode}:{target_id}"
_NEWEST_KEY = "newest_tweet:{mode}:{target_id}"
_PENDING_KEY = "pending:{mode}:{target_id}"


def _validated_config() -> dict:
    from .config import load_config
    cfg = load_config()
    if not cfg.get("auth_token") or not cfg.get("ct0"):
        console.print(Panel(
            "[red]No credentials found.[/red]\n\n"
            "Run first:\n"
            "[bold]xdl config --auth-token <token> --ct0 <ct0>[/bold]\n\n"
            "Get auth_token and ct0 from your browser's DevTools → "
            "Application → Cookies → x.com",
            title="Error",
            border_style="red",
        ))
        raise SystemExit(1)
    return cfg


def _print_summary(scanned: int, media: list[MediaItem]) -> None:
    photos = sum(1 for m in media if m.media_type == "photo")
    gifs = sum(1 for m in media if m.media_type == "animated_gif")
    videos = sum(1 for m in media if m.media_type == "video")
    t = Table.grid(padding=(0, 2))
    t.add_row("Tweets scanned:", f"[bold]{scanned}[/bold]")
    t.add_row("Photos found:", f"[bold]{photos}[/bold]")
    t.add_row("Animated GIFs found:", f"[bold]{gifs}[/bold]")
    t.add_row("Videos found:", f"[bold]{videos}[/bold]")
    console.print(t)


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def _print_done(downloaded: int, skipped: int, folder: "Path | None") -> None:
    location = (
        f"Saved to: [dim]{folder.resolve()}[/dim]" if folder
        else "[dim](SQLite database)[/dim]"
    )
    console.print(Panel(
        f"[green]Downloaded:[/green] [bold]{downloaded}[/bold]   "
        f"[dim]Skipped (already done):[/dim] {skipped}\n"
        f"{location}",
        title="Done ✓",
        border_style="green",
    ))


def _save_pending(db: KVStore, key: str, items: list[MediaItem]) -> None:
    payload = [
        {
            "tweet_id": m.tweet_id,
            "author_id": m.author_id,
            "author_screen_name": m.author_screen_name,
            "author_full_name": m.author_full_name,
            "url": m.url,
            "filename": m.filename,
            "media_type": m.media_type,
        }
        for m in items
    ]
    db.set(key, json.dumps(payload))


def _load_pending(db: KVStore, key: str) -> tuple[list[MediaItem], bool]:
    raw = db.get(key)
    if not raw:
        return [], False
    try:
        data = json.loads(raw)
        items = [MediaItem(**d) for d in data]
        return items, True
    except Exception:
        return [], False


def _check_media_filter(image_only: bool, video_only: bool) -> None:
    """Raise UsageError if mutually exclusive flags are both set."""
    if image_only and video_only:
        raise click.UsageError("--image-only and --video-only cannot be used together.")


def _filter_media(
    items: list[MediaItem],
    image_only: bool,
    video_only: bool,
) -> list[MediaItem]:
    """Apply --image-only / --video-only filter to a list of MediaItems."""
    if image_only:
        return [m for m in items if m.media_type in ("photo", "animated_gif")]
    if video_only:
        return [m for m in items if m.media_type == "video"]
    return items


def _parse_date_option(val: str) -> _date:
    """Parse a YYYY-MM-DD string; raise click.BadParameter if invalid."""
    try:
        return _date.fromisoformat(val)
    except ValueError:
        raise click.BadParameter(f"Invalid date {val!r}. Use YYYY-MM-DD format.")


def _parse_twitter_date(created_at: str) -> _date | None:
    """Parse a Twitter 'created_at' string to a date, or None on failure."""
    if not created_at:
        return None
    try:
        return _datetime.strptime(created_at, "%a %b %d %H:%M:%S +0000 %Y").date()
    except (ValueError, TypeError):
        return None
