"""'import-archive' command — import liked media from an X data archive."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import click

from .._helpers import console, _validated_config
from ..auth import build_headers
from ..client import XClient


@click.command("import-archive")
@click.argument("archive_dir", type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option("--db", "db_path", default=None, help="Target SQLite DB (defaults to config db_path).")
@click.option("--limit", default=0, show_default=True, help="Max tweets to process (0 = all).")
@click.option("--delay", default=0.5, show_default=True, type=float, help="Seconds between API calls.")
@click.option("--concurrency", default=3, show_default=True, type=int, help="Parallel download workers.")
def cmd_import_archive(
    archive_dir: str,
    db_path: Optional[str],
    limit: int,
    delay: float,
    concurrency: int,
) -> None:
    """Import liked media from an X data archive.

    ARCHIVE_DIR is the extracted X archive folder (or its data/ subfolder).
    The archive must contain a like.js file.

    Download the archive from x.com → Settings → Your account → Download an archive.
    """
    asyncio.run(_run_import_archive(archive_dir, db_path, limit, delay, concurrency))


async def _run_import_archive(
    archive_dir: str,
    db_path_arg: Optional[str],
    limit: int,
    delay: float,
    concurrency: int,
) -> None:
    from ..archive import parse_like_ids
    from ..store import SQLiteStore
    from ..media_parser import extract_media
    from ..downloader import fetch_bytes
    from rich.progress import Progress, SpinnerColumn, BarColumn, TaskProgressColumn, TextColumn

    cfg = _validated_config()
    headers = build_headers(cfg["auth_token"], cfg["ct0"], cfg["bearer_token"])
    proxy = cfg.get("proxy") or None

    if db_path_arg:
        db_file = Path(db_path_arg).expanduser().resolve()
    else:
        db_path_str = cfg.get("db_path", "")
        if db_path_str:
            db_file = Path(db_path_str)
        else:
            db_file = Path(cfg.get("output_dir", ".")) / "x-gallery.db"
    store = SQLiteStore(db_file)
    console.print(f"[dim]Target DB: {db_file}[/dim]")

    console.print("[cyan]Parsing archive likes…[/cyan]")
    try:
        all_ids = parse_like_ids(Path(archive_dir))
    except FileNotFoundError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise SystemExit(1)

    console.print(f"[green]✓ Found {len(all_ids)} liked tweet IDs in archive[/green]")

    pending: list[str] = []
    for tid in (all_ids[:limit] if limit else all_ids):
        with store._conn() as conn:
            exists = conn.execute(
                "SELECT 1 FROM media WHERE tweet_id=? LIMIT 1", (tid,)
            ).fetchone() is not None
        if not exists:
            pending.append(tid)

    if not pending:
        console.print("[green]✓ All tweets already downloaded.[/green]")
        return
    console.print(
        f"[cyan]{len(pending)} tweets to fetch "
        f"(skipped {len(all_ids) - len(pending)} already done)…[/cyan]"
    )

    dl_ok = dl_skip = dl_fail = 0
    sem = asyncio.Semaphore(concurrency)

    async def _process(client: "XClient", tweet_id: str) -> None:
        nonlocal dl_ok, dl_skip, dl_fail
        async with sem:
            result = await client.fetch_tweet(tweet_id)
            if result is None:
                dl_fail += 1
                return
            items = extract_media(result)
            if not items:
                dl_skip += 1
                return
            for item in items:
                if store.is_done(item.tweet_id, item.filename):
                    dl_skip += 1
                    continue
                data = await fetch_bytes(item, client._http)
                if data:
                    store.save(item, data)
                    dl_ok += 1
                else:
                    dl_fail += 1
            if delay > 0:
                await asyncio.sleep(delay)

    async with XClient(headers, cfg["query_ids"], proxy=proxy) as client:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
            transient=False,
        ) as progress:
            task = progress.add_task("导入存档", total=len(pending))
            tasks = []
            for tid in pending:
                t = asyncio.create_task(_process(client, tid))
                t.add_done_callback(lambda _: progress.advance(task))
                tasks.append(t)
            await asyncio.gather(*tasks)

    console.print(
        f"[green]✓ 完成: {dl_ok} 文件下载[/green]"
        + (f", {dl_skip} 跳过（无媒体或已存在）" if dl_skip else "")
        + (f", [yellow]{dl_fail} 失败（推文已删除或不可访问）[/yellow]" if dl_fail else "")
    )
