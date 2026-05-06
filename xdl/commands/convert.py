"""'convert' command — convert between folder mode and SQLite mode."""
from __future__ import annotations

from pathlib import Path

import click

from .._helpers import console, _fmt_bytes
from ..gallery import generate_gallery


@click.command("convert")
@click.argument("src")
@click.argument("dst")
def cmd_convert(src: str, dst: str) -> None:
    """Convert between folder mode and SQLite mode.

    \b
    SRC → DST auto-detection:
      folder directory  →  .db file   : import all images into SQLite
      .db file          →  directory  : extract all images to folder tree
    """
    src_p = Path(src).expanduser().resolve()
    dst_p = Path(dst).expanduser().resolve()

    if src_p.is_dir() and (dst_p.suffix == ".db" or not dst_p.exists()):
        _convert_folder_to_sqlite(src_p, dst_p)
    elif src_p.suffix == ".db" and src_p.is_file():
        _convert_sqlite_to_folder(src_p, dst_p)
    else:
        console.print(
            "[red]Cannot determine conversion direction.[/red]\n"
            "  folder → sqlite: [dim]convert <output_dir> <file.db>[/dim]\n"
            "  sqlite → folder: [dim]convert <file.db> <output_dir>[/dim]"
        )
        raise SystemExit(1)


def _convert_folder_to_sqlite(src_dir: Path, dst_db: Path) -> None:
    """Import a folder-based gallery into a SQLite store."""
    from ..gallery import _scan_output_dir
    from ..store import SQLiteStore
    from rich.progress import Progress, SpinnerColumn, BarColumn, TaskProgressColumn, TextColumn

    users = _scan_output_dir(src_dir)
    if not users:
        console.print("[yellow]No user folders found in source directory.[/yellow]")
        return

    total = sum(len(u["files"]) for u in users)
    console.print(
        f"[cyan]Importing {total} files from {len(users)} users "
        f"into [bold]{dst_db}[/bold]…[/cyan]"
    )

    store = SQLiteStore(dst_db)
    imported = 0
    skipped = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Importing…", total=total)
        for u in users:
            folder_path = src_dir / u["folder_name"]
            for filename, media_type in u["files"]:
                file_path = folder_path / filename
                if not file_path.exists():
                    progress.advance(task_id)
                    continue
                synthetic_tweet_id = f"{u['user_id']}_{filename}"
                if store.is_done(synthetic_tweet_id, filename):
                    skipped += 1
                else:
                    store.upsert_user(u["user_id"], u["screen_name"], u["display_name"])
                    store.save_raw(
                        user_id=u["user_id"],
                        tweet_id=synthetic_tweet_id,
                        filename=filename,
                        media_type=media_type,
                        url="",
                        data=file_path.read_bytes(),
                    )
                    imported += 1
                progress.advance(task_id)

    console.print(
        f"[green]Imported:[/green] [bold]{imported}[/bold]   "
        f"[dim]Skipped (already in DB):[/dim] {skipped}\n"
        f"Database: [dim]{dst_db}[/dim]"
    )


def _convert_sqlite_to_folder(src_db: Path, dst_dir: Path) -> None:
    """Extract a SQLite store into a folder-based gallery."""
    from ..store import SQLiteStore
    from ..media_parser import _safe_name as _sfn
    from rich.progress import Progress, SpinnerColumn, BarColumn, TaskProgressColumn, TextColumn

    store = SQLiteStore(src_db)
    users = store.list_users()
    if not users:
        console.print("[yellow]No media found in the database.[/yellow]")
        return

    total = sum(u["media_count"] for u in users)
    console.print(
        f"[cyan]Extracting {total} files from {len(users)} users "
        f"into [bold]{dst_dir}[/bold]…[/cyan]"
    )
    dst_dir.mkdir(parents=True, exist_ok=True)

    extracted = 0
    skipped = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Extracting…", total=total)
        for u in users:
            safe_display = _sfn(u["display_name"] or u["screen_name"] or u["user_id"])
            folder_name = f"{safe_display}_{u['screen_name'] or ''}_{u['user_id']}"
            folder_path = dst_dir / folder_name
            folder_path.mkdir(parents=True, exist_ok=True)
            for m in store.list_media(u["user_id"]):
                dest = folder_path / m["filename"]
                if dest.exists():
                    skipped += 1
                else:
                    data = store.get_media_blob(u["user_id"], m["filename"])
                    if data:
                        dest.write_bytes(data)
                        extracted += 1
                progress.advance(task_id)

    generate_gallery(dst_dir)
    console.print(
        f"[green]Extracted:[/green] [bold]{extracted}[/bold]   "
        f"[dim]Skipped (already exists):[/dim] {skipped}\n"
        f"Output: [dim]{dst_dir}[/dim]"
    )
