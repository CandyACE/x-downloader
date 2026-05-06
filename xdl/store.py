"""SQLite media store — single-file alternative to folder-based storage.

All images and videos are stored as BLOBs inside a single .db file,
so no folder tree is visible on disk.

Schema
------
users  — one row per unique author
media  — one row per downloaded file (tweet_id + filename must be unique)
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from .media_parser import MediaItem


class SQLiteStore:
    """Read/write media to a self-contained SQLite database."""

    def __init__(self, db_path: Path) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._setup()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @contextmanager
    def _conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _setup(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id           INTEGER PRIMARY KEY,
                    user_id      TEXT UNIQUE NOT NULL,
                    screen_name  TEXT,
                    display_name TEXT
                );

                CREATE TABLE IF NOT EXISTS media (
                    id            INTEGER PRIMARY KEY,
                    user_id       TEXT NOT NULL,
                    tweet_id      TEXT NOT NULL,
                    filename      TEXT NOT NULL,
                    media_type    TEXT NOT NULL,
                    url           TEXT,
                    data          BLOB NOT NULL,
                    downloaded_at TEXT DEFAULT (datetime('now')),
                    UNIQUE(tweet_id, filename)
                );

                CREATE INDEX IF NOT EXISTS idx_media_user ON media(user_id);
                CREATE INDEX IF NOT EXISTS idx_media_tweet ON media(tweet_id);

                CREATE TABLE IF NOT EXISTS thumbnails (
                    user_id  TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    data     BLOB NOT NULL,
                    PRIMARY KEY (user_id, filename)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT
                );
            """)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def is_done(self, tweet_id: str, filename: str) -> bool:
        """Return True if this file is already in the store."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT 1 FROM media WHERE tweet_id=? AND filename=?",
                (tweet_id, filename),
            ).fetchone() is not None

    def upsert_user(
        self,
        user_id: str,
        screen_name: str,
        display_name: str,
    ) -> None:
        """Insert or update a user record."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, screen_name, display_name)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    screen_name  = excluded.screen_name,
                    display_name = excluded.display_name
                """,
                (user_id, screen_name, display_name),
            )

    def save(self, item: MediaItem, data: bytes) -> None:
        """Store a downloaded media item as a BLOB (upserts author record in same transaction)."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO users (user_id, screen_name, display_name)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    screen_name  = excluded.screen_name,
                    display_name = excluded.display_name
                """,
                (item.author_id, item.author_screen_name, item.author_full_name),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO media
                    (user_id, tweet_id, filename, media_type, url, data)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item.author_id,
                    item.tweet_id,
                    item.filename,
                    item.media_type,
                    item.url,
                    data,
                ),
            )

    def save_raw(
        self,
        *,
        user_id: str,
        tweet_id: str,
        filename: str,
        media_type: str,
        url: str,
        data: bytes,
    ) -> None:
        """Low-level insert: store raw bytes without a MediaItem object."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO media
                    (user_id, tweet_id, filename, media_type, url, data)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, tweet_id, filename, media_type, url, data),
            )

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list_users(self) -> list[dict]:
        """Return all users that have at least one media file, with file counts."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT u.user_id, u.screen_name, u.display_name,
                       COUNT(m.id) AS media_count,
                       MAX(m.downloaded_at) AS latest_at
                FROM users u
                JOIN media m ON m.user_id = u.user_id
                GROUP BY u.user_id
                ORDER BY u.display_name, u.screen_name
                """
            ).fetchall()
        return [dict(r) for r in rows]

    def list_media(self, user_id: str) -> list[dict]:
        """Return metadata (no BLOB) for all files belonging to *user_id*."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT filename, media_type, tweet_id FROM media WHERE user_id=? ORDER BY id",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_media_with_thumbs(self, user_id: str) -> list[dict]:
        """Return metadata for all files, with a ``has_thumb`` boolean flag."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT m.filename, m.media_type, m.tweet_id,
                       CASE WHEN t.user_id IS NOT NULL THEN 1 ELSE 0 END AS has_thumb
                FROM media m
                LEFT JOIN thumbnails t
                       ON t.user_id = m.user_id AND t.filename = m.filename
                WHERE m.user_id = ?
                ORDER BY m.id
                """,
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_media_preview(self, user_id: str, limit: int = 6) -> list[dict]:
        """Return the first *limit* file metadata rows for use as card thumbnails."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT m.filename, m.media_type, m.tweet_id,
                       CASE WHEN t.user_id IS NOT NULL THEN 1 ELSE 0 END AS has_thumb
                FROM media m
                LEFT JOIN thumbnails t
                       ON t.user_id = m.user_id AND t.filename = m.filename
                WHERE m.user_id = ?
                ORDER BY m.id
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_media_blob(self, user_id: str, filename: str) -> bytes | None:
        """Fetch the raw bytes for a single file, or None if not found."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT data FROM media WHERE user_id=? AND filename=?",
                (user_id, filename),
            ).fetchone()
        return bytes(row["data"]) if row else None

    def delete_user(self, user_id: str) -> int:
        """Delete a user and all their media/thumbnails. Returns media rows deleted."""
        with self._conn() as conn:
            n = conn.execute("DELETE FROM media WHERE user_id=?", (user_id,)).rowcount
            conn.execute("DELETE FROM thumbnails WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM users WHERE user_id=?", (user_id,))
        return n

    def delete_media(self, user_id: str, filename: str) -> bool:
        """Delete a single media item and its thumbnail. Returns True if deleted."""
        with self._conn() as conn:
            n = conn.execute(
                "DELETE FROM media WHERE user_id=? AND filename=?", (user_id, filename)
            ).rowcount
            conn.execute(
                "DELETE FROM thumbnails WHERE user_id=? AND filename=?", (user_id, filename)
            )
        return n > 0

    # ------------------------------------------------------------------
    # Thumbnails
    # ------------------------------------------------------------------

    def has_thumb(self, user_id: str, filename: str) -> bool:
        """Return True if a thumbnail exists for this file."""
        with self._conn() as conn:
            return conn.execute(
                "SELECT 1 FROM thumbnails WHERE user_id=? AND filename=?",
                (user_id, filename),
            ).fetchone() is not None

    def save_thumb(self, user_id: str, filename: str, jpeg: bytes) -> None:
        """Store (or replace) a JPEG thumbnail."""
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO thumbnails (user_id, filename, data) VALUES (?,?,?)",
                (user_id, filename, jpeg),
            )

    def get_thumb_blob(self, user_id: str, filename: str) -> bytes | None:
        """Fetch a thumbnail's JPEG bytes, or None if not found."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT data FROM thumbnails WHERE user_id=? AND filename=?",
                (user_id, filename),
            ).fetchone()
        return bytes(row["data"]) if row else None

    def stats(self) -> dict:
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM media").fetchone()[0]
            authors = conn.execute("SELECT COUNT(DISTINCT user_id) FROM media").fetchone()[0]
        return {"total_files": total, "unique_authors": authors}

    def list_users_with_stats(self) -> list[dict]:
        """Return all users with detailed stats (file count, total bytes, type breakdown)."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT u.user_id, u.screen_name, u.display_name,
                       COUNT(m.id) AS file_count,
                       COALESCE(SUM(LENGTH(m.data)), 0) AS total_bytes,
                       SUM(CASE WHEN m.media_type='photo' THEN 1 ELSE 0 END) AS photo_count,
                       SUM(CASE WHEN m.media_type='animated_gif' THEN 1 ELSE 0 END) AS gif_count,
                       SUM(CASE WHEN m.media_type='video' THEN 1 ELSE 0 END) AS video_count
                FROM users u
                JOIN media m ON m.user_id = u.user_id
                GROUP BY u.user_id
                ORDER BY total_bytes DESC
                """
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # KV state store (cursors, newest tweet IDs, pending queues)
    # These mirror DownloadDB.get/set/delete so a thin adapter can be used.
    # ------------------------------------------------------------------

    def get(self, key: str) -> str | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key=?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set(self, key: str, value: str | None) -> None:
        if value is None:
            with self._conn() as conn:
                conn.execute("DELETE FROM settings WHERE key=?", (key,))
        else:
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)",
                    (key, value),
                )

    def delete(self, key: str) -> None:
        self.set(key, None)
