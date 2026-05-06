"""SQLite-backed download history for incremental and resume support.

Stored at {output_dir}/.x-dl-history.db
Tables:
  downloads  — every successfully downloaded file
  state      — generic key/value store (cursors, newest tweet IDs, etc.)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class KVStore(Protocol):
    """Structural protocol for key-value state stores.

    Both :class:`DownloadDB` and :class:`~xdl.store.SQLiteStore` satisfy this
    protocol, so either can be used wherever cursor / pending-queue state is
    read or written.
    """

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str | None) -> None: ...
    def delete(self, key: str) -> None: ...


class DownloadDB:
    def __init__(self, db_path: Path) -> None:
        self._path = db_path
        self._setup()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _setup(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS downloads (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    tweet_id     TEXT NOT NULL,
                    author_id    TEXT NOT NULL,
                    filename     TEXT NOT NULL,
                    media_type   TEXT NOT NULL,
                    created_at   TEXT DEFAULT (datetime('now')),
                    UNIQUE(tweet_id, filename)
                );
                CREATE INDEX IF NOT EXISTS idx_dl_tweet ON downloads(tweet_id);
                CREATE TABLE IF NOT EXISTS state (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );
            """)

    # ------------------------------------------------------------------
    # Download records
    # ------------------------------------------------------------------

    def is_done(self, tweet_id: str, filename: str) -> bool:
        """Return True if this specific file was already downloaded."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT 1 FROM downloads WHERE tweet_id=? AND filename=?",
                (tweet_id, filename),
            ).fetchone() is not None

    def mark_done(
        self, tweet_id: str, author_id: str, filename: str, media_type: str
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO downloads"
                " (tweet_id, author_id, filename, media_type) VALUES (?,?,?,?)",
                (tweet_id, author_id, filename, media_type),
            )

    def is_tweet_seen(self, tweet_id: str) -> bool:
        """Return True if any file from this tweet has been downloaded before."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT 1 FROM downloads WHERE tweet_id=?", (tweet_id,)
            ).fetchone() is not None

    # ------------------------------------------------------------------
    # State (cursors, newest tweet IDs, pending queues)
    # ------------------------------------------------------------------

    def get(self, key: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
            return row["value"] if row else None

    def set(self, key: str, value: str | None) -> None:
        if value is None:
            with self._conn() as conn:
                conn.execute("DELETE FROM state WHERE key=?", (key,))
        else:
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO state (key, value) VALUES (?,?)",
                    (key, value),
                )

    def delete(self, key: str) -> None:
        self.set(key, None)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
            authors = conn.execute(
                "SELECT COUNT(DISTINCT author_id) FROM downloads"
            ).fetchone()[0]
            return {"total_files": total, "unique_authors": authors}
