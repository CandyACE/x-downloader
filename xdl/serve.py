"""Built-in HTTP gallery server for the SQLite storage mode.

Usage:
    xdl serve <path>

<path> can be:
  - a .db file created by SQLiteStore → serves from the database
  - a directory containing an index.html → serves static files

The server opens the browser automatically after binding the port.
"""
from __future__ import annotations

import gzip as _gzip
import hashlib
import json as _json
import mimetypes
import queue as _queue
import subprocess as _subprocess
import sys as _sys
import threading as _threading
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

_MEDIA_CACHE_CONTROL = "public, max-age=86400, immutable"


def _guess_ctype(filename: str) -> str:
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return _EXTRA_TYPES.get(ext) or mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _etag(user_id: str, filename: str) -> str:
    """Stable ETag for a stored media file (content is immutable once written)."""
    h = hashlib.sha1(
        f"{user_id}\x00{filename}".encode(), usedforsecurity=False
    ).hexdigest()
    return f'"{h[:20]}"'


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

    def _send_json(self, body: bytes, *, head_only: bool = False) -> None:
        """Send a JSON response, gzip-compressed when the client accepts it."""
        accept_enc = self.headers.get("Accept-Encoding", "")  # type: ignore[attr-defined]
        if "gzip" in accept_enc:
            payload = _gzip.compress(body, compresslevel=1)
            self.send_response(200)  # type: ignore[attr-defined]
            self.send_header("Content-Type", "application/json; charset=utf-8")  # type: ignore[attr-defined]
            self.send_header("Content-Encoding", "gzip")  # type: ignore[attr-defined]
            self.send_header("Content-Length", str(len(payload)))  # type: ignore[attr-defined]
            self.send_header("Vary", "Accept-Encoding")  # type: ignore[attr-defined]
            self.send_header("Cache-Control", "no-cache")  # type: ignore[attr-defined]
            self.end_headers()  # type: ignore[attr-defined]
            if not head_only:
                self.wfile.write(payload)  # type: ignore[attr-defined]
        else:
            self.send_response(200)  # type: ignore[attr-defined]
            self.send_header("Content-Type", "application/json; charset=utf-8")  # type: ignore[attr-defined]
            self.send_header("Content-Length", str(len(body)))  # type: ignore[attr-defined]
            self.send_header("Cache-Control", "no-cache")  # type: ignore[attr-defined]
            self.end_headers()  # type: ignore[attr-defined]
            if not head_only:
                self.wfile.write(body)  # type: ignore[attr-defined]

    def _send_media(self, ctype: str, data: bytes, *, head_only: bool = False, etag: str = "") -> None:
        """Send *data* with Content-Type *ctype*, honouring any Range header.

        Attaches ``Cache-Control`` and ``ETag`` headers so browsers cache the
        blob and avoid re-fetching it on every virtual-scroll cycle.
        """
        total = len(data)
        range_hdr = self.headers.get("Range", "")  # type: ignore[attr-defined]

        def _common(status: int, length: int, start: int = 0, end: int = -1) -> None:
            self.send_response(status)  # type: ignore[attr-defined]
            self.send_header("Content-Type", ctype)  # type: ignore[attr-defined]
            self.send_header("Content-Length", str(length))  # type: ignore[attr-defined]
            self.send_header("Accept-Ranges", "bytes")  # type: ignore[attr-defined]
            self.send_header("Cache-Control", _MEDIA_CACHE_CONTROL)  # type: ignore[attr-defined]
            if etag:
                self.send_header("ETag", etag)  # type: ignore[attr-defined]
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")  # type: ignore[attr-defined]
            self.end_headers()  # type: ignore[attr-defined]

        if range_hdr.startswith("bytes="):
            try:
                spec = range_hdr[6:].split(",")[0].strip()
                start_s, end_s = spec.split("-", 1)
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else total - 1
                end = min(end, total - 1)
                chunk = data[start : end + 1]
                _common(206, len(chunk), start, end)
                if not head_only:
                    self.wfile.write(chunk)  # type: ignore[attr-defined]
                return
            except (ValueError, IndexError):
                pass  # fall through to full response

        _common(200, total)
        if not head_only:
            self.wfile.write(data)  # type: ignore[attr-defined]

    def _send_media_stream(
        self,
        ctype: str,
        total: int,
        read_chunk,
        *,
        head_only: bool = False,
        etag: str = "",
        chunk_size: int = 1 << 20,
    ) -> None:
        """Like :meth:`_send_media` but streams the body in chunks.

        *read_chunk(offset, length)* returns up to *length* bytes from the
        media starting at *offset*, so large videos never get fully loaded
        into memory — only ``chunk_size`` bytes are held at a time.
        """
        range_hdr = self.headers.get("Range", "")  # type: ignore[attr-defined]

        def _common(status: int, length: int, start: int = 0, end: int = -1) -> None:
            self.send_response(status)  # type: ignore[attr-defined]
            self.send_header("Content-Type", ctype)  # type: ignore[attr-defined]
            self.send_header("Content-Length", str(length))  # type: ignore[attr-defined]
            self.send_header("Accept-Ranges", "bytes")  # type: ignore[attr-defined]
            self.send_header("Cache-Control", _MEDIA_CACHE_CONTROL)  # type: ignore[attr-defined]
            if etag:
                self.send_header("ETag", etag)  # type: ignore[attr-defined]
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")  # type: ignore[attr-defined]
            self.end_headers()  # type: ignore[attr-defined]

        def _pump(start: int, length: int) -> None:
            remaining = length
            pos = start
            while remaining > 0:
                buf = read_chunk(pos, min(chunk_size, remaining))
                if not buf:
                    break
                try:
                    self.wfile.write(buf)  # type: ignore[attr-defined]
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    # Browsers routinely abort Range requests (seeking, etc.)
                    break
                pos += len(buf)
                remaining -= len(buf)

        if range_hdr.startswith("bytes="):
            try:
                spec = range_hdr[6:].split(",")[0].strip()
                start_s, end_s = spec.split("-", 1)
                start = int(start_s) if start_s else 0
                end = int(end_s) if end_s else total - 1
                end = min(end, total - 1)
                if start > end or start < 0:
                    raise ValueError
                length = end - start + 1
                _common(206, length, start, end)
                if not head_only:
                    _pump(start, length)
                return
            except (ValueError, IndexError):
                pass  # fall through to full response

        _common(200, total)
        if not head_only:
            _pump(0, total)


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

    def do_PUT(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        if path == "/api/favorites":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b"{}"
            self.__class__.store.set("gallery_favorites_v1", body.decode("utf-8"))
            self._send(200, "application/json", b'{"ok":true}')
        else:
            self._send(404, "text/plain", b"Not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        if path == "/api/task/start":
            self._handle_task_start()
        else:
            self._send(404, "text/plain", b"Not found")

    def _handle(self, head_only: bool = False) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)

        if path in ("/", "/index.html"):
            self._serve_gallery(head_only)
        elif path == "/api/users":
            self._serve_api_users(head_only)
        elif path == "/api/favorites":
            self._serve_api_favorites(head_only)
        elif path == "/api/task/status":
            self._serve_api_task_status()
        elif path == "/api/task/stream":
            self._serve_api_task_stream()
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
        result = []
        for u in store.list_users_with_previews():
            preview = [
                {
                    "f": m["filename"],
                    "t": "video" if m["media_type"] in ("video", "animated_gif") else "image",
                    "ht": int(m["has_thumb"]),
                }
                for m in u["preview"]
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
        self._send_json(body, head_only=head_only)

    def _serve_api_favorites(self, head_only: bool = False) -> None:
        raw = self.__class__.store.get("gallery_favorites_v1") or "{}"
        self._send_json(raw.encode("utf-8"), head_only=head_only)

    # ------------------------------------------------------------------
    # Task (download/update) endpoints
    # ------------------------------------------------------------------

    def _handle_task_start(self) -> None:
        cls = self.__class__
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b"{}"
        try:
            data = _json.loads(body)
        except Exception:
            self._send(400, "application/json", b'{"error":"bad json"}')
            return

        with cls._task_lock:
            if cls._task["running"]:
                self._send(409, "application/json", b'{"error":"task already running"}')
                return

        cmd = data.get("cmd", "")
        db_path = str(cls.store._path)
        args = data.get("args", {})

        # Build subprocess argv
        try:
            argv = _build_task_argv(cmd, db_path, args)
        except ValueError as exc:
            err = _json.dumps({"error": str(exc)}).encode()
            self._send(400, "application/json", err)
            return

        env = {**__import__("os").environ, "NO_COLOR": "1", "FORCE_COLOR": "0"}
        proc = _subprocess.Popen(
            argv,
            stdout=_subprocess.PIPE,
            stderr=_subprocess.STDOUT,
            env=env,
        )

        with cls._task_lock:
            cls._task.update({
                "proc": proc,
                "running": True,
                "exit_code": None,
                "log": [],
                "subs": [],
            })

        _threading.Thread(
            target=_task_reader,
            args=(proc, cls._task, cls._task_lock),
            daemon=True,
        ).start()

        self._send(200, "application/json", b'{"ok":true}')

    def _serve_api_task_status(self) -> None:
        cls = self.__class__
        with cls._task_lock:
            running = cls._task["running"]
            exit_code = cls._task["exit_code"]
        body = _json.dumps({"running": running, "exit_code": exit_code}, separators=(",", ":")).encode()
        self._send(200, "application/json", body)

    def _serve_api_task_stream(self) -> None:
        cls = self.__class__
        q: _queue.Queue = _queue.Queue()

        # Replay existing log lines first, then subscribe
        with cls._task_lock:
            backlog = list(cls._task["log"])
            already_done = not cls._task["running"] and cls._task["exit_code"] is not None
            exit_code = cls._task["exit_code"]
            if not already_done:
                cls._task["subs"].append(q)

        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            def write_sse(event: str | None, data: str) -> bool:
                try:
                    chunk = ""
                    if event:
                        chunk += f"event: {event}\n"
                    chunk += f"data: {data}\n\n"
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
                    return True
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return False

            for line in backlog:
                if not write_sse(None, line):
                    return

            if already_done:
                write_sse("done", _json.dumps({"exit": exit_code}, separators=(",", ":")))
                return

            while True:
                try:
                    kind, val = q.get(timeout=15)
                except _queue.Empty:
                    if not write_sse("ping", ""):
                        break
                    continue
                if kind == "log":
                    if not write_sse(None, val):
                        break
                elif kind == "done":
                    write_sse("done", _json.dumps({"exit": val}, separators=(",", ":")))
                    break
        finally:
            with cls._task_lock:
                try:
                    cls._task["subs"].remove(q)
                except ValueError:
                    pass


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
        self._send_json(body, head_only=head_only)

    def _serve_media(self, tail: str, head_only: bool = False) -> None:
        """Serve ``/media/{user_id}/{filename}`` from the database."""
        parts = tail.split("/", 1)
        if len(parts) != 2:
            self._send(400, "text/plain", b"Bad media path")
            return
        user_id, filename = parts
        tag = _etag(user_id, filename)
        if self.headers.get("If-None-Match") == tag:
            self.send_response(304)
            self.send_header("ETag", tag)
            self.send_header("Cache-Control", _MEDIA_CACHE_CONTROL)
            self.end_headers()
            return
        data = self.__class__.store.get_media_rowid_size(user_id, filename)
        if not data:
            self._send(404, "text/plain", b"Not found")
            return
        rowid, size = data
        ctype = _guess_ctype(filename)
        store = self.__class__.store
        self._send_media_stream(
            ctype,
            size,
            lambda off, ln: store.read_media_chunk(rowid, off, ln),
            head_only=head_only,
            etag=tag,
        )

    def _serve_thumb(self, tail: str, head_only: bool = False) -> None:
        """Serve ``/thumb/{user_id}/{filename}`` — a pre-generated JPEG thumbnail."""
        parts = tail.split("/", 1)
        if len(parts) != 2:
            self._send(400, "text/plain", b"Bad thumb path")
            return
        user_id, filename = parts
        tag = _etag(user_id, filename)
        if self.headers.get("If-None-Match") == tag:
            self.send_response(304)
            self.send_header("ETag", tag)
            self.send_header("Cache-Control", _MEDIA_CACHE_CONTROL)
            self.end_headers()
            return
        data = self.__class__.store.get_thumb_blob(user_id, filename)
        if not data:
            self._send(404, "text/plain", b"Not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", _MEDIA_CACHE_CONTROL)
        self.send_header("ETag", tag)
        self.end_headers()
        if not head_only:
            self.wfile.write(data)


def _build_task_argv(cmd: str, db_path: str, args: dict) -> list[str]:
    """Build a subprocess argv list for the requested download command."""
    base = [_sys.executable, "-m", "xdl"]
    if cmd == "user":
        username = args.get("username", "").strip().lstrip("@")
        if not username:
            raise ValueError("用户名不能为空")
        argv = base + ["user", username, "--single", "--db", db_path]
        limit = str(args.get("limit", 0) or 0)
        if limit != "0":
            argv += ["--limit", limit]
        if args.get("full"):
            argv += ["--full"]
        if args.get("media_type") == "image":
            argv += ["--image-only"]
        elif args.get("media_type") == "video":
            argv += ["--video-only"]
        return argv
    if cmd == "tweet":
        raw = args.get("ids", "").strip()
        if not raw:
            raise ValueError("推文ID/URL不能为空")
        ids = [x.strip() for x in raw.splitlines() if x.strip()]
        if not ids:
            raise ValueError("推文ID/URL不能为空")
        argv = base + ["tweet"] + ids + ["--db", db_path]
        if args.get("media_type") == "image":
            argv += ["--image-only"]
        elif args.get("media_type") == "video":
            argv += ["--video-only"]
        return argv
    if cmd == "likes":
        argv = base + ["likes", "--db", db_path]
        if args.get("me"):
            argv += ["--me", args["me"].strip().lstrip("@")]
        limit = str(args.get("limit", 0) or 0)
        if limit != "0":
            argv += ["--limit", limit]
        if args.get("full"):
            argv += ["--full"]
        if args.get("media_type") == "image":
            argv += ["--image-only"]
        elif args.get("media_type") == "video":
            argv += ["--video-only"]
        return argv
    if cmd == "merge-db":
        src = args.get("src", "").strip()
        if not src:
            raise ValueError("源DB路径不能为空")
        return base + ["merge-db", "--from", src, "--to", db_path, "--yes"]
    raise ValueError(f"未知命令: {cmd!r}")


def _task_reader(proc: "_subprocess.Popen[bytes]", task: dict, lock: "_threading.Lock") -> None:
    """Background thread: read subprocess output line-by-line and broadcast to SSE subscribers."""
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.decode("utf-8", errors="replace").rstrip("\n\r")
        with lock:
            task["log"].append(line)
            for q in task["subs"]:
                q.put(("log", line))
    proc.wait()
    with lock:
        task["running"] = False
        task["exit_code"] = proc.returncode
        for q in task["subs"]:
            q.put(("done", proc.returncode))


def _make_sqlite_handler(store: "SQLiteStore") -> type:
    """Return a handler class with *store* and task state bound as class attributes."""
    task_state: dict = {
        "proc": None,
        "running": False,
        "exit_code": None,
        "log": [],
        "subs": [],
    }
    return type("_BoundSQLiteHandler", (_SQLiteHandler,), {
        "store": store,
        "_task": task_state,
        "_task_lock": _threading.Lock(),
    })


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
# Quiet server — suppresses client-disconnect tracebacks
# ---------------------------------------------------------------------------

class _QuietServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that silently ignores client-disconnect errors.

    Browsers routinely abort in-flight requests (fast scrolling, navigation,
    prefetch cancellation). These produce ConnectionAbortedError /
    ConnectionResetError / BrokenPipeError that are harmless but noisy.
    """

    def handle_error(self, request, client_address) -> None:  # type: ignore[override]
        import sys
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)


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

    server = _QuietServer(("127.0.0.1", port), handler_cls)
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
