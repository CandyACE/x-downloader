"""'tweet' command — download media from one or more tweets by ID or URL."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Optional

import click

from .._helpers import _check_media_filter, _filter_media, _print_done, _validated_config, console
from ..auth import build_headers
from ..client import XClient
from ..db import DownloadDB
from ..downloader import download_all
from ..gallery import generate_gallery
from ..media_parser import MediaItem, _safe_name as _sfn, extract_media


def _parse_tweet_id(value: str) -> str:
    """Extract numeric tweet ID from a URL or return the raw value."""
    m = re.search(r'/status/(\d+)', value)
    if m:
        return m.group(1)
    if re.fullmatch(r'\d+', value.strip()):
        return value.strip()
    raise click.BadParameter(
        f"Cannot parse tweet ID from {value!r}. "
        "Pass a numeric ID or a URL like https://x.com/user/status/1234567890"
    )


@click.command("tweet")
@click.argument("tweet_ids_or_urls", nargs=-1, required=False)
@click.option(
    "--file", "ids_file", default=None,
    type=click.Path(exists=True, dir_okay=False),
    help="Text file with one tweet ID or URL per line",
)
@click.option("--output", default=None, help="Override output directory")
@click.option(
    "--mode", default=None, type=click.Choice(["folder", "sqlite"]),
    help="Storage mode: folder (default) or sqlite",
)
@click.option(
    "--single", is_flag=True, default=False,
    help="Store in a single SQLite .db file (shorthand for --mode sqlite)",
)
@click.option("--db", default=None, help="Path to .db file (sqlite mode)")
@click.option("--image-only", "image_only", is_flag=True, default=False,
              help="Download only images and GIFs (skip videos)")
@click.option("--video-only", "video_only", is_flag=True, default=False,
              help="Download only videos (skip images/GIFs)")
def cmd_tweet(
    tweet_ids_or_urls: tuple[str, ...],
    ids_file: Optional[str],
    output: Optional[str],
    mode: Optional[str],
    single: bool,
    db: Optional[str],
    image_only: bool,
    video_only: bool,
) -> None:
    """Download media from one or more tweets by ID or URL.

    TWEET_IDS_OR_URLS accepts numeric tweet IDs or full X/Twitter URLs:

    \b
      xdl tweet 1234567890
      xdl tweet https://x.com/user/status/1234567890
      xdl tweet 111 222 333
      xdl tweet --file tweets.txt
    """
    _check_media_filter(image_only, video_only)

    # Collect raw values from positional args and --file
    raw: list[str] = list(tweet_ids_or_urls)
    if ids_file:
        lines = Path(ids_file).read_text(encoding="utf-8").splitlines()
        raw.extend(line.strip() for line in lines if line.strip())

    if not raw:
        console.print(
            "[bold red]Error:[/bold red] Provide at least one tweet ID/URL, "
            "or use --file <path>."
        )
        raise SystemExit(1)

    # Normalize first, then deduplicate (catches URL vs bare-ID duplicates)
    tweet_ids: list[str] = []
    errors: list[str] = []
    seen: set[str] = set()
    for val in raw:
        try:
            tid = _parse_tweet_id(val)
        except click.BadParameter as exc:
            errors.append(str(exc))
            continue
        if tid not in seen:
            seen.add(tid)
            tweet_ids.append(tid)

    for err in errors:
        console.print(f"[bold red]Error:[/bold red] {err}")
    if not tweet_ids:
        raise SystemExit(1)

    try:
        asyncio.run(_run_tweets(tweet_ids, output, mode, single, db, image_only, video_only))
    except RuntimeError as exc:
        console.print(f"\n[bold red]Error:[/bold red] {exc}")
        raise SystemExit(1)


async def _run_tweets(
    tweet_ids: list[str],
    output_override: Optional[str],
    storage_mode: Optional[str],
    single: bool,
    db_path: Optional[str],
    image_only: bool = False,
    video_only: bool = False,
) -> None:
    cfg = _validated_config()
    headers = build_headers(cfg["auth_token"], cfg["ct0"], cfg["bearer_token"])
    eff_mode = "sqlite" if single else (storage_mode or cfg.get("storage_mode", "folder"))

    store = None
    if eff_mode == "sqlite":
        from ..store import SQLiteStore
        if db_path:
            _db_file = Path(db_path).expanduser()
        elif cfg.get("db_path"):
            _db_file = Path(cfg["db_path"]).expanduser()
        else:
            _out = Path(output_override or cfg["output_dir"])
            _db_file = _out.parent / (_out.name + ".db")
        store = SQLiteStore(_db_file)
        console.print(f"[dim]SQLite mode: {_db_file}[/dim]")
        output_dir = None
        db = store
    else:
        output_dir = Path(output_override or cfg["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        db = DownloadDB(output_dir / ".x-dl-history.db")

    proxy = cfg.get("proxy") or None
    total = len(tweet_ids)
    all_downloaded = all_skipped = 0
    folders_created: set[str] = set()

    async with XClient(headers, cfg["query_ids"], proxy=proxy) as client:
        for i, tweet_id in enumerate(tweet_ids, 1):
            if total > 1:
                console.print(f"\n[cyan]── Tweet {i}/{total}: {tweet_id}…[/cyan]")
            else:
                console.print(f"[cyan]Fetching tweet {tweet_id}…[/cyan]")

            try:
                result = await client.fetch_tweet(tweet_id)
            except RuntimeError:
                raise  # auth errors propagate to caller
            except Exception as exc:
                console.print(f"[yellow]⚠ Tweet {tweet_id} error: {exc} — skipping.[/yellow]")
                continue

            if result is None:
                console.print(
                    f"[yellow]⚠ Tweet {tweet_id} not found "
                    "(may be deleted, private, or incorrect ID) — skipping.[/yellow]"
                )
                continue

            items: list[MediaItem] = extract_media(result)
            items = _filter_media(items, image_only, video_only)

            if not items:
                console.print(f"[yellow]No downloadable media in tweet {tweet_id}.[/yellow]")
                continue

            console.print(
                f"[green]✓ Found {len(items)} media item(s) "
                f"from @{items[0].author_screen_name}[/green]"
            )

            author = items[0]
            folder_name = (
                f"{_sfn(author.author_full_name)}_{author.author_screen_name}_{author.author_id}"
            )
            folders_created.add(folder_name)

            downloaded, skipped = await download_all(
                items,
                output_dir,
                headers,
                db,
                concurrency=cfg["concurrency"],
                mode="user",
                folder_name=folder_name,
                proxy=proxy,
                store=store,
            )
            all_downloaded += downloaded
            all_skipped += skipped

            if total == 1:
                if store is None:
                    _print_done(downloaded, skipped, output_dir / folder_name)
                else:
                    _print_done(downloaded, skipped, None)

    if total > 1:
        console.print(
            f"\n[bold green]✓ Done:[/bold green] "
            f"{all_downloaded} downloaded, {all_skipped} skipped "
            f"across {total} tweet(s)."
        )
        if store is None and output_dir:
            _print_done(all_downloaded, all_skipped, output_dir)
        elif store is None:
            pass
        else:
            _print_done(all_downloaded, all_skipped, None)

    if store is None and folders_created and output_dir:
        generate_gallery(output_dir)
