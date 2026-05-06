"""'user' command — download images/GIFs from a target user's tweets."""
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
from ..media_parser import MediaItem, _safe_name as _sfn, extract_media


@click.command("user")
@click.argument("username")
@click.option("--output", default=None, help="Override output directory")
@click.option(
    "--limit", default=0, type=int,
    help="Stop after scanning this many tweets (0 = all)"
)
@click.option(
    "--full", is_flag=True, default=False,
    help="Ignore incremental history and re-scan all tweets"
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
@click.option("--media-only", "media_only", is_flag=True, default=False,
              help="Use the UserMedia endpoint (Media tab only, no text-only tweets)")
@click.option("--image-only", "image_only", is_flag=True, default=False,
              help="Download only images and GIFs (skip videos)")
@click.option("--video-only", "video_only", is_flag=True, default=False,
              help="Download only videos (skip images/GIFs)")
@click.option("--since", "since", default=None, metavar="DATE",
              help="Only download tweets on or after DATE (YYYY-MM-DD)")
@click.option("--until", "until", default=None, metavar="DATE",
              help="Only download tweets on or before DATE (YYYY-MM-DD)")
def cmd_user(
    username: str, output: Optional[str], limit: int, full: bool,
    mode: Optional[str], single: bool, db: Optional[str],
    scan_delay: Optional[float], debug: bool, media_only: bool,
    image_only: bool, video_only: bool,
    since: Optional[str], until: Optional[str],
) -> None:
    """Download images/GIFs from USERNAME's tweets.

    Files are saved to: OUTPUT_DIR/{user_id}/  (folder mode)
    or into a single .db file  (--single / --mode sqlite).

    On subsequent runs only new tweets are fetched (incremental mode).
    Use --full to force a complete re-scan.
    Use --media-only to query the Media tab endpoint instead of the full timeline.
    """
    try:
        _check_media_filter(image_only, video_only)
        since_date = _parse_date_option(since) if since else None
        until_date = _parse_date_option(until) if until else None
        asyncio.run(_run_user(username, output, limit, full, mode, single, db, scan_delay, debug, media_only, image_only, video_only, since_date, until_date))
    except RuntimeError as exc:
        console.print(f"\n[bold red]Error:[/bold red] {exc}")
        raise SystemExit(1)


async def _run_user(
    username: str, output_override: Optional[str], limit: int, full: bool,
    storage_mode: Optional[str] = None, single: bool = False,
    db_path: Optional[str] = None,
    scan_delay: Optional[float] = None, debug: bool = False,
    media_only: bool = False,
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
        console.print(f"[cyan]Looking up @{username}…[/cyan]")
        user_id, screen_name, full_name = await client.get_user_id(username)
        console.print(f"[green]✓ Found: @{screen_name} — {full_name} (ID: {user_id})[/green]")

        safe_full = _sfn(full_name)
        user_folder = f"{safe_full}_{screen_name}_{user_id}"

        feed_mode = "user_media" if media_only else "user"
        cursor_key = _CURSOR_KEY.format(mode=feed_mode, target_id=user_id)
        newest_key = _NEWEST_KEY.format(mode=feed_mode, target_id=user_id)
        pending_key = _PENDING_KEY.format(mode=feed_mode, target_id=user_id)

        # --- Resume: check for saved pending items from an interrupted run ---
        all_media, resumed = _load_pending(db, pending_key)
        if resumed:
            all_media = _filter_media(all_media, image_only, video_only)
            console.print(
                f"[yellow]↩ Resuming interrupted session "
                f"({len(all_media)} pending items).[/yellow]"
            )

        if not resumed:
            # --- Incremental: start from saved cursor / stop at known tweet ---
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

                    with Status("[cyan]Scanning tweets…[/cyan]", console=console) as status:
                        async def _status_upd_user() -> None:
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
                                        f"[cyan]Scanning tweets…[/cyan] "
                                        f"{scanned} tweets | {photos_found} photos | {gifs_found} GIFs | {videos_found} videos"
                                        + _suffix
                                    )
                                    await asyncio.sleep(0.5)
                                except asyncio.CancelledError:
                                    return

                        _upd_task = asyncio.create_task(_status_upd_user())
                        _iter = (
                            client.iter_user_media if media_only else client.iter_user_tweets
                        )
                        async for tweet in _iter(
                            user_id, start_cursor=start_cursor, on_cursor=_save_cursor,
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
                                    download_one(item, cdn, output_dir, db, cdn_sem, "user", user_folder, store)
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

                # Save newest tweet ID for next incremental run
                if newest_tweet:
                    db.set(newest_key, newest_tweet)

                # Clear cursor only on complete (non-interrupted) fetch
                if not stopped_early:
                    db.delete(cursor_key)

                _print_summary(scanned, all_media)
                _save_pending(db, pending_key, all_media)

                # Drain any remaining download tasks with a progress bar
                downloaded, skipped = await drain_download_tasks(download_tasks)

            db.delete(pending_key)
            if store is None:
                _print_done(downloaded, skipped, output_dir / user_folder)
                generate_gallery(output_dir)
            else:
                _print_done(downloaded, skipped, None)
            return

    # Resumed path: use batch download (DB deduplication skips already-done files)
    downloaded, skipped = await download_all(
        all_media, output_dir, headers, db,
        concurrency=cfg["concurrency"],
        mode="user",
        folder_name=user_folder,
        proxy=proxy,
        store=store,
    )
    db.delete(pending_key)
    if store is None:
        _print_done(downloaded, skipped, output_dir / user_folder)
        generate_gallery(output_dir)
    else:
        _print_done(downloaded, skipped, None)
