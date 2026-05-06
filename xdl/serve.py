"""Built-in HTTP gallery server for the SQLite storage mode.

Usage:
    xdl serve <path>

<path> can be:
  - a .db file created by SQLiteStore → serves from the database
  - a directory containing an index.html → serves static files

The server opens the browser automatically after binding the port.
"""
from __future__ import annotations

import mimetypes
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from rich.console import Console

console = Console()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_EXTRA_TYPES: dict[str, str] = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".gif": "image/gif",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _guess_ctype(filename: str) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _EXTRA_TYPES.get(ext) or mimetypes.guess_type(filename)[0] or "application/octet-stream"


# ---------------------------------------------------------------------------
# SQLite-backed handler
# ---------------------------------------------------------------------------

class _RangeMixin:
    """Mixin that adds HTTP Range-request support for binary media responses."""

    def _send(self, status: int, ctype: str, body: bytes, *, head_only: bool = False) -> None:
        self.send_response(status)  # type: ignore[attr-defined]
        self.send_header("Content-Type", ctype)  # type: ignore[attr-defined]
        self.send_header("Content-Length", str(len(body)))  # type: ignore[attr-defined]
        self.end_headers()  # type: ignore[attr-defined]
        if not head_only:
            self.wfile.write(body)  # type: ignore[attr-defined]

    def _send_media(self, ctype: str, data: bytes, *, head_only: bool = False) -> None:
        """Send *data* with Content-Type *ctype*, honouring any Range header."""
        total = len(data)
        range_hdr = self.headers.get("Range", "")  # type: ignore[attr-defined]

        if range_hdr.startswith("bytes="):
            try:
                spec = range_hdr[6:].split(",")[0].strip()
                start_s, end_s = spec.split("-", 1)
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else total - 1
                end = min(end, total - 1)
                chunk = data[start : end + 1]
                self.send_response(206)  # type: ignore[attr-defined]
                self.send_header("Content-Type", ctype)  # type: ignore[attr-defined]
                self.send_header("Content-Length", str(len(chunk)))  # type: ignore[attr-defined]
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")  # type: ignore[attr-defined]
                self.send_header("Accept-Ranges", "bytes")  # type: ignore[attr-defined]
                self.end_headers()  # type: ignore[attr-defined]
                if not head_only:
                    self.wfile.write(chunk)  # type: ignore[attr-defined]
                return
            except (ValueError, IndexError):
                pass  # fall through to full response

        self.send_response(200)  # type: ignore[attr-defined]
        self.send_header("Content-Type", ctype)  # type: ignore[attr-defined]
        self.send_header("Content-Length", str(total))  # type: ignore[attr-defined]
        self.send_header("Accept-Ranges", "bytes")  # type: ignore[attr-defined]
        self.end_headers()  # type: ignore[attr-defined]
        if not head_only:
            self.wfile.write(data)  # type: ignore[attr-defined]


class _SQLiteHandler(_RangeMixin, BaseHTTPRequestHandler):
    """HTTP handler that serves gallery HTML and BLOB data from a SQLiteStore."""

    store: "SQLiteStore"  # injected by _make_sqlite_handler()

    def log_message(self, fmt: str, *args) -> None:  # type: ignore[override]
        pass  # suppress default request logging

    def do_GET(self) -> None:  # noqa: N802
        self._handle(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle(head_only=True)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        parts = urllib.parse.unquote(parsed.path).strip("/").split("/")
        store = self.__class__.store
        if parts[:2] == ["api", "user"] and len(parts) == 3:
            n = store.delete_user(parts[2])
            self._send(200, "application/json", f'{{"deleted":{n}}}'.encode())
        elif parts[:2] == ["api", "media"] and len(parts) == 4:
            ok = store.delete_media(parts[2], parts[3])
            self._send(200, "application/json", f'{{"ok":{"true" if ok else "false"}}}'.encode())
        else:
            self._send(404, "text/plain", b"Not found")

    def _handle(self, head_only: bool = False) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)

        if path in ("/", "/index.html"):
            self._serve_gallery(head_only)
        elif path == "/api/users":
            self._serve_api_users(head_only)
        elif path.startswith("/api/media/"):
            self._serve_api_media(path[len("/api/media/"):], head_only)
        elif path.startswith("/media/"):
            self._serve_media(path[len("/media/"):], head_only)
        elif path.startswith("/thumb/"):
            self._serve_thumb(path[len("/thumb/"):], head_only)
        else:
            self._send(404, "text/plain", b"Not found")

    def _serve_gallery(self, head_only: bool = False) -> None:
        from .gallery import build_gallery_html
        html = build_gallery_html([], media_base="/media", thumb_base="/thumb", api_mode=True)
        self._send(200, "text/html; charset=utf-8", html.encode("utf-8"), head_only=head_only)

    def _serve_api_users(self, head_only: bool = False) -> None:
        import json as _json
        store = self.__class__.store
        from .gallery import _snowflake_ms
        result = []
        for u in store.list_users():
            preview = [
                {
                    "f": m["filename"],
                    "t": "video" if m["media_type"] in ("video", "animated_gif") else "image",
                    "ht": bool(m["has_thumb"]),
                }
                for m in store.list_media_preview(u["user_id"])
            ]
            result.append({
                "uid": u["user_id"],
                "display": u["display_name"] or u["screen_name"] or u["user_id"],
                "screen": u["screen_name"] or "",
                "count": u["media_count"],
                "latest": u.get("latest_at") or "",
                "preview": preview,
            })
        body = _json.dumps(result, separators=(",", ":")).encode("utf-8")
        self._send(200, "application/json; charset=utf-8", body, head_only=head_only)

    def _serve_api_media(self, tail: str, head_only: bool = False) -> None:
        import json as _json
        uid = urllib.parse.unquote(tail.strip("/"))
        if not uid:
            self._send(400, "text/plain", b"Missing user_id")
            return
        store = self.__class__.store
        from .gallery import _snowflake_ms
        result = []
        for m in store.list_media_with_thumbs(uid):
            t_norm = "video" if m["media_type"] in ("video", "animated_gif") else "image"
            ts = _snowflake_ms(m["tweet_id"]) if m.get("tweet_id") else 0
            item: dict = {"f": m["filename"], "t": t_norm}
            if ts:
                item["ts"] = ts
            if m.get("tweet_id"):
                item["tid"] = m["tweet_id"]
            if m["has_thumb"]:
                item["ht"] = 1
            result.append(item)
        body = _json.dumps(result, separators=(",", ":")).encode("utf-8")
        self._send(200, "application/json; charset=utf-8", body, head_only=head_only)

    def _serve_media(self, tail: str, head_only: bool = False) -> None:
        """Serve ``/media/{user_id}/{filename}`` from the database."""
        parts = tail.split("/", 1)
        if len(parts) != 2:
            self._send(400, "text/plain", b"Bad media path")
            return
        user_id, filename = parts
        data = self.__class__.store.get_media_blob(user_id, filename)
        if not data:
            self._send(404, "text/plain", b"Not found")
            return
        ctype = _guess_ctype(filename)
        self._send_media(ctype, data, head_only=head_only)

    def _serve_thumb(self, tail: str, head_only: bool = False) -> None:
        """Serve ``/thumb/{user_id}/{filename}`` — a pre-generated JPEG thumbnail."""
        parts = tail.split("/", 1)
        if len(parts) != 2:
            self._send(400, "text/plain", b"Bad thumb path")
            return
        user_id, filename = parts
        data = self.__class__.store.get_thumb_blob(user_id, filename)
        if not data:
            self._send(404, "text/plain", b"Not found")
            return
        self._send(200, "image/jpeg", data, head_only=head_only)


def _make_sqlite_handler(store: "SQLiteStore") -> type:
    """Return a handler class with *store* bound as a class attribute."""
    return type("_BoundSQLiteHandler", (_SQLiteHandler,), {"store": store})


# ---------------------------------------------------------------------------
# Static folder handler
# ---------------------------------------------------------------------------

class _FolderHandler(_RangeMixin, BaseHTTPRequestHandler):
    """Serve files from a directory (folder-mode gallery)."""

    root: Path  # injected

    def log_message(self, fmt: str, *args) -> None:  # type: ignore[override]
        pass

    def do_GET(self) -> None:  # noqa: N802
        self._handle(head_only=False)

    def do_HEAD(self) -> None:  # noqa: N802
        self._handle(head_only=True)

    def _handle(self, head_only: bool = False) -> None:
        parsed = urllib.parse.urlparse(self.path)
        rel = urllib.parse.unquote(parsed.path).lstrip("/") or "index.html"
        target = (self.__class__.root / rel).resolve()
        # Safety: ensure the resolved path is within root
        try:
            target.relative_to(self.__class__.root.resolve())
        except ValueError:
            self.send_response(403)
            self.end_headers()
            return

        if not target.is_file():
            self.send_response(404)
            self.end_headers()
            return

        data = target.read_bytes()
        ctype = _guess_ctype(target.name)
        self._send_media(ctype, data, head_only=head_only)


def _make_folder_handler(root: Path) -> type:
    return type("_BoundFolderHandler", (_FolderHandler,), {"root": root})


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def serve(path: str, port: int = 0) -> None:
    """
    Start the gallery HTTP server.

    *path*  — either a ``.db`` file (SQLite mode) or a directory (folder mode).
    *port*  — 0 = let OS pick a free port (default).
    """
    target = Path(path).expanduser().resolve()

    if target.suffix == ".db":
        from .store import SQLiteStore
        store = SQLiteStore(target)
        handler_cls = _make_sqlite_handler(store)
        label = f"SQLite: {target.name}"
    elif target.is_dir():
        if not (target / "index.html").exists():
            console.print(f"[red]No index.html found in {target}[/red]")
            return
        handler_cls = _make_folder_handler(target)
        label = f"folder: {target}"
    else:
        console.print(f"[red]Path must be a .db file or a directory: {target}[/red]")
        return

    server = ThreadingHTTPServer(("127.0.0.1", port), handler_cls)
    actual_port = server.server_address[1]
    url = f"http://127.0.0.1:{actual_port}/"

    console.print(f"[green]✓ Gallery server running[/green] ({label})")
    console.print(f"  [cyan]{url}[/cyan]  — press Ctrl+C to stop\n")

    # Open browser in background after a short delay
    Thread(target=lambda: (
        __import__("time").sleep(0.4),
        webbrowser.open(url),
    ), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]Server stopped.[/dim]")
    finally:
        server.server_close()
