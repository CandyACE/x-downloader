"""'thumbs' command — pre-generate video/GIF thumbnails in a SQLite gallery DB."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from .._helpers import console
from ..config import load_config


@click.command("thumbs")
@click.argument("db", required=False, default=None)
@click.option("--force", is_flag=True, default=False, help="Regenerate thumbnails that already exist.")
def cmd_thumbs(db: Optional[str], force: bool) -> None:
    """Pre-generate video/GIF thumbnails in a SQLite gallery DB.

    DB defaults to the db_path in config (or output_dir/x-gallery.db).
    Thumbnails are stored back into the same .db file and served by
    ``xdl serve`` at ``/thumb/{user_id}/{filename}``.
    """
    from ..store import SQLiteStore
    from ..thumb import extract_frame
    from rich.progress import Progress, SpinnerColumn, BarColumn, TaskProgressColumn, TextColumn

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

    jobs: list[tuple[str, str]] = []  # (user_id, filename)
    for u in store.list_users():
        for m in store.list_media_with_thumbs(u["user_id"]):
            if m["media_type"] not in ("video", "animated_gif"):
                continue
            if not force and m["has_thumb"]:
                continue
            jobs.append((u["user_id"], m["filename"]))

    if not jobs:
        console.print("[green]✓ All thumbnails are up-to-date.[/green]")
        return

    console.print(f"[cyan]{len(jobs)} 个视频需要生成缩略图…[/cyan]")
    done = failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("生成缩略图", total=len(jobs))
        for user_id, filename in jobs:
            progress.update(task, description=f"[dim]{filename[:40]}[/dim]")
            data = store.get_media_blob(user_id, filename)
            if not data:
                failed += 1
                progress.advance(task)
                continue
            jpeg = extract_frame(data)
            if jpeg:
                store.save_thumb(user_id, filename, jpeg)
                done += 1
            else:
                failed += 1
            progress.advance(task)

    console.print(
        f"[green]✓ 完成: {done} 成功[/green]"
        + (f", [yellow]{failed} 失败[/yellow]" if failed else "")
    )
