"""'stats' command — show download statistics from a SQLite gallery DB."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import click
from rich.table import Table

from .._helpers import console, _fmt_bytes
from ..config import load_config


@click.command("stats")
@click.argument("db", required=False, default=None)
def cmd_stats(db: Optional[str]) -> None:
    """Show download statistics from a SQLite gallery DB.

    DB defaults to the db_path in config (or output_dir/x-gallery.db).
    """
    from ..store import SQLiteStore

    cfg = load_config()
    if db:
        db_path = Path(db).expanduser().resolve()
    else:
        db_path_str = cfg.get("db_path", "")
        if db_path_str:
            db_path = Path(db_path_str)
        else:
            output_dir = cfg.get("output_dir", "")
            db_path = Path(output_dir) / "x-gallery.db" if output_dir else None

    if not db_path or not db_path.is_file():
        console.print(
            "[red]✗ DB not found.[/red] "
            "Pass a [bold].db[/bold] file or set [bold]config --db[/bold]."
        )
        raise SystemExit(1)

    store = SQLiteStore(db_path)
    users = store.list_users_with_stats()
    if not users:
        console.print("[yellow]No data found in the database.[/yellow]")
        return

    table = Table(title=f"X Gallery Stats — {db_path.name}", show_lines=False)
    table.add_column("用户", style="bold", no_wrap=True)
    table.add_column("@Handle", style="dim")
    table.add_column("合计", justify="right")
    table.add_column("图片", justify="right")
    table.add_column("GIF", justify="right")
    table.add_column("视频", justify="right")
    table.add_column("大小", justify="right")

    total_files = 0
    total_bytes = 0
    total_photos = total_gifs = total_videos = 0
    for u in users:
        total_files += u["file_count"]
        total_bytes += u["total_bytes"]
        total_photos += u.get("photo_count", 0)
        total_gifs += u.get("gif_count", 0)
        total_videos += u.get("video_count", 0)
        table.add_row(
            u["display_name"] or u["screen_name"] or u["user_id"],
            f"@{u['screen_name']}" if u["screen_name"] else u["user_id"],
            str(u["file_count"]),
            str(u.get("photo_count", 0)) if u.get("photo_count") else "[dim]—[/dim]",
            str(u.get("gif_count", 0)) if u.get("gif_count") else "[dim]—[/dim]",
            str(u.get("video_count", 0)) if u.get("video_count") else "[dim]—[/dim]",
            _fmt_bytes(u["total_bytes"]),
        )

    table.add_section()
    table.add_row(
        "[bold]合计[/bold]", "",
        f"[bold]{total_files}[/bold]",
        f"[bold]{total_photos}[/bold]",
        f"[bold]{total_gifs}[/bold]",
        f"[bold]{total_videos}[/bold]",
        f"[bold]{_fmt_bytes(total_bytes)}[/bold]",
    )
    console.print(table)
