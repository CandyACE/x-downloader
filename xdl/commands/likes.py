"""'likes' command — download images/GIFs from liked tweets."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import click
import httpx
from rich.status import Status

from .._helpers import (
    KVStore,
    _CURSOR_KEY,
    _NEWEST_KEY,
    _PENDING_KEY,
    _check_media_filter,
    _filter_media,
    _load_pending,
    _parse_date_option,
    _parse_twitter_date,
    _print_done,
    _print_summary,
    _save_pending,
    _validated_config,
    console,
)
from ..auth import build_headers
from ..client import XClient
from ..db import DownloadDB
from ..downloader import download_all, download_one, drain_download_tasks, make_cdn_headers
from ..gallery import generate_gallery
from ..media_parser import MediaItem, extract_media


@click.command("likes")
@click.option("--output", default=None, help="Override output directory")
@click.option(
    "--limit", default=0, type=int,
    help="Stop after scanning this many liked tweets (0 = all)"
)
@click.option(
    "--full", is_flag=True, default=False,
    help="Ignore incremental history and re-scan all liked tweets"
)
@click.option(
    "--me", default=None,
    help="Your X username (skips auto-detection if get_me fails)"
)
@click.option(
    "--mode", default=None, type=click.Choice(["folder", "sqlite"]),
    help="Storage mode: folder (default) or sqlite"
)
@click.option(
    "--single", is_flag=True, default=False,
    help="Store everything in a single SQLite .db file (shorthand for --mode sqlite)"
)
@click.option(
    "--db", default=None,
    help="Path to .db file (sqlite mode; default: <output>.db)"
)
@click.option(
    "--scan-delay", default=None, type=float,
    help="Seconds between API pages (default 1.0; 0 = no delay)"
)
@click.option("--debug", is_flag=True, default=False, help="Print each API page fetch/response")
@click.option("--image-only", "image_only", is_flag=True, default=False,
              help="Download only images and GIFs (skip videos)")
@click.option("--video-only", "video_only", is_flag=True, default=False,
              help="Download only videos (skip images/GIFs)")
@click.option("--since", "since", default=None, metavar="DATE",
              help="Only download tweets on or after DATE (YYYY-MM-DD)")
@click.option("--until", "until", default=None, metavar="DATE",
              help="Only download tweets on or before DATE (YYYY-MM-DD)")
def cmd_likes(
    output: Optional[str], limit: int, full: bool, me: Optional[str],
    mode: Optional[str], single: bool, db: Optional[str],
    scan_delay: Optional[float], debug: bool,
    image_only: bool, video_only: bool,
    since: Optional[str], until: Optional[str],
) -> None:
    """Download images/GIFs from your liked tweets.

    Files are organised by original author: OUTPUT_DIR/{author_id}/  (folder mode)
    or stored in a single .db file  (--single / --mode sqlite).

    On subsequent runs only new likes are fetched (incremental mode).
    Use --full to force a complete re-scan.
    If auto-detection fails, provide your username with --me yourname.
    """
    try:
        _check_media_filter(image_only, video_only)
        since_date = _parse_date_option(since) if since else None
        until_date = _parse_date_option(until) if until else None
        asyncio.run(_run_likes(output, limit, full, me, mode, single, db, scan_delay, debug, image_only, video_only, since_date, until_date))
    except RuntimeError as exc:
        console.print(f"\n[bold red]Error:[/bold red] {exc}")
        raise SystemExit(1)


async def _run_likes(
    output_override: Optional[str], limit: int, full: bool,
    me_username: Optional[str] = None,
    storage_mode: Optional[str] = None, single: bool = False,
    db_path: Optional[str] = None,
    scan_delay: Optional[float] = None, debug: bool = False,
    image_only: bool = False,
    video_only: bool = False,
    since_date=None,
    until_date=None,
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
        db: KVStore = store
    else:
        output_dir = Path(output_override or cfg["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        db = DownloadDB(output_dir / ".x-dl-history.db")

    proxy = cfg.get("proxy") or None
    page_delay = scan_delay if scan_delay is not None else float(cfg.get("scan_delay", 1.0))

    async with XClient(headers, cfg["query_ids"], proxy=proxy) as client:
        if me_username:
            console.print(f"[cyan]Looking up @{me_username}…[/cyan]")
            my_id, my_screen, _my_full = await client.get_user_id(me_username)
        else:
            console.print("[cyan]Fetching your account info…[/cyan]")
            try:
                my_id, my_screen, _my_full = await client.get_me()
            except Exception as exc:
                console.print(
                    f"[red]✗ Auto-detection failed: {exc}[/red]\n"
                    "[yellow]Tip: run with [bold]--me your_username[/bold] to skip auto-detection[/yellow]"
                )
                raise SystemExit(1)
        console.print(f"[green]✓ Account: @{my_screen} (ID: {my_id})[/green]")

        mode = "likes"
        cursor_key = _CURSOR_KEY.format(mode=mode, target_id=my_id)
        newest_key = _NEWEST_KEY.format(mode=mode, target_id=my_id)
        pending_key = _PENDING_KEY.format(mode=mode, target_id=my_id)

        # --- Resume check ---
        all_media, resumed = _load_pending(db, pending_key)
        if resumed:
            all_media = _filter_media(all_media, image_only, video_only)
            console.print(
                f"[yellow]↩ Resuming interrupted session "
                f"({len(all_media)} pending items).[/yellow]"
            )

        if not resumed:
            start_cursor = None if full else db.get(cursor_key)
            stop_tweet_id = None if full else db.get(newest_key)

            if start_cursor:
                console.print(
                    "[yellow]↩ Resuming API pagination from saved cursor.[/yellow]"
                )
            if stop_tweet_id:
                console.print(
                    f"[cyan]ℹ Incremental mode: will stop at tweet {stop_tweet_id}[/cyan]"
                )

            all_media = []
            newest_tweet: str | None = None
            scanned = 0
            photos_found = 0
            gifs_found = 0
            videos_found = 0
            stopped_early = False
            download_tasks: list[asyncio.Task] = []

            cdn_sem = asyncio.Semaphore(cfg["concurrency"])
            async with httpx.AsyncClient(
                headers=make_cdn_headers(headers),
                follow_redirects=True, timeout=60.0, proxy=proxy,
            ) as cdn:
                _upd_task: asyncio.Task | None = None
                try:
                    def _save_cursor(cursor: str) -> None:
                        db.set(cursor_key, cursor)

                    with Status("[cyan]Scanning likes…[/cyan]", console=console) as status:
                        async def _status_upd_likes() -> None:
                            while True:
                                try:
                                    done = [t for t in download_tasks if t.done() and not t.cancelled()]
                                    _dl = _sk = 0
                                    for _t in done:
                                        try:
                                            _ok, _skip = _t.result()
                                            if _ok: _dl += 1
                                            elif _skip: _sk += 1
                                        except Exception:
                                            pass
                                    _suffix = ""
                                    if _dl or _sk:
                                        _suffix = f" | [green]{_dl}↓[/green]"
                                        if _sk: _suffix += f" [dim]{_sk} skip[/dim]"
                                    status.update(
                                        f"[cyan]Scanning likes…[/cyan] "
                                        f"{scanned} tweets | {photos_found} photos | {gifs_found} GIFs | {videos_found} videos"
                                        + _suffix
                                    )
                                    await asyncio.sleep(0.5)
                                except asyncio.CancelledError:
                                    return

                        _upd_task = asyncio.create_task(_status_upd_likes())
                        async for tweet in client.iter_likes(
                            my_id, start_cursor=start_cursor, on_cursor=_save_cursor,
                            page_delay=page_delay, verbose=debug,
                        ):
                            tweet_id = tweet.get("legacy", {}).get("id_str", "")
                            if newest_tweet is None and tweet_id:
                                newest_tweet = tweet_id

                            if stop_tweet_id and tweet_id == stop_tweet_id:
                                console.print(
                                    "[cyan]ℹ Reached previously downloaded tweets — stopping.[/cyan]"
                                )
                                stopped_early = True
                                break

                            # Date range filtering
                            if since_date or until_date:
                                tweet_date = _parse_twitter_date(
                                    tweet.get("legacy", {}).get("created_at", "")
                                )
                                if tweet_date is None:
                                    scanned += 1
                                    continue  # skip tweets with unparseable dates
                                if until_date and tweet_date > until_date:
                                    scanned += 1
                                    continue  # too new, skip but keep scanning
                                if since_date and tweet_date < since_date:
                                    break  # too old, stop (normal completion, cursor cleared)

                            new_items = extract_media(tweet)
                            new_items = _filter_media(new_items, image_only, video_only)
                            all_media.extend(new_items)
                            for item in new_items:
                                t = asyncio.create_task(
                                    download_one(item, cdn, output_dir, db, cdn_sem, "likes", "", store)
                                )
                                download_tasks.append(t)
                            scanned += 1
                            photos_found += sum(1 for m in new_items if m.media_type == "photo")
                            gifs_found += sum(1 for m in new_items if m.media_type == "animated_gif")
                            videos_found += sum(1 for m in new_items if m.media_type == "video")
                            if limit and scanned >= limit:
                                break

                except KeyboardInterrupt:
                    if _upd_task:
                        _upd_task.cancel()
                    console.print("\n[yellow]⚠ Interrupted. Saving progress…[/yellow]")
                    for t in download_tasks:
                        t.cancel()
                    await asyncio.gather(*download_tasks, return_exceptions=True)
                    _save_pending(db, pending_key, all_media)
                    raise SystemExit(0)

                if _upd_task:
                    _upd_task.cancel()
                    await asyncio.gather(_upd_task, return_exceptions=True)

                if newest_tweet:
                    db.set(newest_key, newest_tweet)

                if not stopped_early:
                    db.delete(cursor_key)

                _print_summary(scanned, all_media)
                _save_pending(db, pending_key, all_media)

                downloaded, skipped = await drain_download_tasks(download_tasks)

            db.delete(pending_key)
            if store is None:
                _print_done(downloaded, skipped, output_dir)
                generate_gallery(output_dir)
            else:
                _print_done(downloaded, skipped, None)
            return

    downloaded, skipped = await download_all(
        all_media, output_dir, headers, db,
        concurrency=cfg["concurrency"],
        mode="likes",
        proxy=proxy,
        store=store,
    )
    db.delete(pending_key)
    if store is None:
        _print_done(downloaded, skipped, output_dir)
        generate_gallery(output_dir)
    else:
        _print_done(downloaded, skipped, None)
