"""Async concurrent media downloader with folder organization."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import aiofiles
import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from .db import DownloadDB
from .media_parser import MediaItem

if TYPE_CHECKING:
    from .store import SQLiteStore

console = Console()

# Headers that belong to the X API session — strip before hitting CDN
_STRIP_HEADERS: frozenset[str] = frozenset({
    "authorization", "x-csrf-token", "x-twitter-active-user",
    "x-twitter-auth-type", "x-twitter-client-language",
    "content-type", "cookie",
})


def make_cdn_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a copy of *headers* without X API session fields."""
    return {k: v for k, v in headers.items() if k.lower() not in _STRIP_HEADERS}


def _dest_folder(item: MediaItem, output_dir: Path, mode: str, folder_name: str) -> Path:
    if mode == "likes":
        return output_dir / f"{item.author_full_name}_{item.author_screen_name}_{item.author_id}"
    return output_dir / (folder_name or item.author_id)


async def fetch_bytes(item: MediaItem, http: httpx.AsyncClient, *, retries: int = 3) -> bytes | None:
    """Fetch the raw bytes for a single MediaItem, with exponential-backoff retry.

    Retries on HTTP 429/5xx and transient network/timeout errors.
    Only logs on the final failure to avoid cluttering progress output.
    Returns None on failure.
    """
    _RETRIABLE_STATUS = frozenset({429, 500, 502, 503, 504})
    last_exc: Exception | None = None

    for attempt in range(retries + 1):
        try:
            resp = await http.get(item.url)
            resp.raise_for_status()
            return resp.content
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            if attempt < retries and code in _RETRIABLE_STATUS:
                retry_after = exc.response.headers.get("Retry-After", "")
                wait = float(retry_after) if retry_after.isdigit() else (2 ** attempt)
                last_exc = exc
                await asyncio.sleep(wait)
                continue
            console.print(f"[red]✗ {item.filename}: HTTP {code}[/red]")
            return None
        except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as exc:
            if attempt < retries:
                last_exc = exc
                await asyncio.sleep(2 ** attempt)
                continue
            console.print(f"[red]✗ {item.filename}: {exc}[/red]")
            return None
        except Exception as exc:
            console.print(f"[red]✗ {item.filename}: {exc}[/red]")
            return None

    # Exhausted retries via the transient-error path
    console.print(f"[red]✗ {item.filename}: {last_exc}[/red]")
    return None


async def download_one(
    item: MediaItem,
    http: httpx.AsyncClient,
    output_dir: Path | None,
    db: DownloadDB,
    semaphore: asyncio.Semaphore,
    mode: str,
    folder_name: str,
    store: "SQLiteStore | None" = None,
) -> tuple[bool, bool]:
    """Download a single MediaItem. Returns (downloaded, skipped)."""
    if store is not None:
        if store.is_done(item.tweet_id, item.filename):
            return False, True
    elif db.is_done(item.tweet_id, item.filename):
        return False, True

    if store is None:
        assert output_dir is not None
        folder = _dest_folder(item, output_dir, mode, folder_name)
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / item.filename
        if dest.exists():
            db.mark_done(item.tweet_id, item.author_id, item.filename, item.media_type)
            return False, True

    async with semaphore:
        data = await fetch_bytes(item, http)
        if data is None:
            return False, False
        if store is not None:
            store.save(item, data)
        else:
            assert output_dir is not None
            folder = _dest_folder(item, output_dir, mode, folder_name)
            dest = folder / item.filename
            async with aiofiles.open(dest, "wb") as f:
                await f.write(data)
            db.mark_done(item.tweet_id, item.author_id, item.filename, item.media_type)
        return True, False


async def drain_download_tasks(tasks: list[asyncio.Task]) -> tuple[int, int]:
    """
    Await any not-yet-done tasks from *tasks* with a Rich progress bar.

    Returns (downloaded_count, skipped_count) aggregated over ALL tasks.
    """
    pending = [t for t in tasks if not t.done()]
    total = len(tasks)

    # Tally already-finished tasks before showing the progress bar
    downloaded = skipped = 0
    for t in tasks:
        if t.done() and not t.cancelled():
            try:
                ok, skip = t.result()
                if ok:
                    downloaded += 1
                elif skip:
                    skipped += 1
            except Exception:
                pass

    def _desc() -> str:
        d = f"Downloading… [green]{downloaded}↓[/green]"
        if skipped:
            d += f"  [dim]{skipped} skipped[/dim]"
        return d

    if pending:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            prog_id = progress.add_task(_desc(), total=total)
            # Advance past already-finished tasks
            progress.advance(prog_id, total - len(pending))
            for fut in asyncio.as_completed(pending):
                try:
                    ok, skip = await fut
                    if ok:
                        downloaded += 1
                    elif skip:
                        skipped += 1
                except Exception:
                    pass
                progress.update(prog_id, advance=1, description=_desc())

    return downloaded, skipped


async def download_all(
    items: list[MediaItem],
    output_dir: Path | None,
    headers: dict[str, str],
    db: DownloadDB,
    *,
    concurrency: int = 5,
    mode: str = "user",
    folder_name: str = "",
    proxy: str | None = None,
    store: "SQLiteStore | None" = None,
) -> tuple[int, int]:
    """
    Download all *items* concurrently.

    *store*: if provided, save media as BLOBs into the SQLite store instead of
    writing to *output_dir*.  *output_dir* may be None when using a store.

    Returns (downloaded_count, skipped_count).
    """
    if not items:
        return 0, 0

    semaphore = asyncio.Semaphore(concurrency)
    downloaded = 0
    skipped = 0

    async with httpx.AsyncClient(
        headers=make_cdn_headers(headers), follow_redirects=True, timeout=60.0, proxy=proxy
    ) as http:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task_id = progress.add_task("Downloading…", total=len(items))

            async def _task(item: MediaItem) -> None:
                nonlocal downloaded, skipped
                ok, skip = await download_one(
                    item, http, output_dir, db, semaphore, mode, folder_name, store
                )
                if ok:
                    downloaded += 1
                elif skip:
                    skipped += 1
                progress.advance(task_id)

            await asyncio.gather(*[_task(item) for item in items])

    return downloaded, skipped
