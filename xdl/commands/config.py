"""'config' command — save credentials and settings, browser-based login."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import click

from .._helpers import console
from ..config import get_config_path, load_config, save_config


# ---------------------------------------------------------------------------
# Browser-based auth capture (CDP)
# ---------------------------------------------------------------------------

def _find_browser() -> str | None:
    """Return path to Chrome or Edge executable, or None if not found."""
    import os, shutil
    if sys.platform == "win32":
        candidates = [
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
    elif sys.platform == "darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        ]
    else:
        candidates = [
            shutil.which(b) for b in
            ["google-chrome", "chromium-browser", "chromium", "microsoft-edge"]
        ]
    for path in candidates:
        if path and Path(path).exists():
            return path
    return None


def _find_free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _cdp_ws_connect(host: str, port: int, path: str):
    """Open a raw socket and perform the WebSocket upgrade handshake."""
    import socket, base64, os
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(10)
    sock.connect((host, port))
    key = base64.b64encode(os.urandom(16)).decode()
    handshake = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Upgrade: websocket\r\n"
        f"Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n"
        f"\r\n"
    )
    sock.sendall(handshake.encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        resp += sock.recv(4096)
    if b"101" not in resp:
        sock.close()
        raise RuntimeError(f"WebSocket upgrade failed: {resp[:200]!r}")
    sock.settimeout(15)
    return sock


def _cdp_ws_send(sock, message: str) -> None:
    import os, struct
    data = message.encode()
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    ln = len(data)
    if ln <= 125:
        header = bytes([0x81, 0x80 | ln]) + mask
    elif ln <= 65535:
        header = bytes([0x81, 0xFE]) + struct.pack(">H", ln) + mask
    else:
        header = bytes([0x81, 0xFF]) + struct.pack(">Q", ln) + mask
    sock.sendall(header + masked)


def _cdp_ws_recv(sock) -> str:
    import struct
    payload = b""
    while True:
        hdr = b""
        while len(hdr) < 2:
            hdr += sock.recv(2 - len(hdr))
        fin = bool(hdr[0] & 0x80)
        opcode = hdr[0] & 0x0F
        masked = bool(hdr[1] & 0x80)
        length = hdr[1] & 0x7F
        if length == 126:
            buf = b""
            while len(buf) < 2:
                buf += sock.recv(2 - len(buf))
            length = struct.unpack(">H", buf)[0]
        elif length == 127:
            buf = b""
            while len(buf) < 8:
                buf += sock.recv(8 - len(buf))
            length = struct.unpack(">Q", buf)[0]
        chunk = b""
        while len(chunk) < length:
            chunk += sock.recv(length - len(chunk))
        if masked:
            mk = chunk[:4]
            chunk = bytes(b ^ mk[i % 4] for i, b in enumerate(chunk[4:]))
        payload += chunk
        if fin:
            break
    return payload.decode()


def _capture_auth_via_cdp() -> dict[str, str]:
    """Launch Chrome/Edge with CDP, wait for X login, return auth cookies."""
    import subprocess, tempfile, time, urllib.request, shutil

    browser = _find_browser()
    if not browser:
        raise RuntimeError(
            "Chrome or Edge not found. Install Chrome or Edge and try again."
        )

    cdp_port = _find_free_port()
    user_data_dir = tempfile.mkdtemp(prefix="x-dl-login-")

    console.print(f"[dim]Browser: {browser}[/dim]")
    console.print(f"[dim]CDP port: {cdp_port}[/dim]")

    proc = subprocess.Popen(
        [
            browser,
            f"--remote-debugging-port={cdp_port}",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "https://x.com/login",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        console.print("[yellow]Waiting for browser to start…[/yellow]")
        for _ in range(30):
            try:
                urllib.request.urlopen(
                    f"http://localhost:{cdp_port}/json/version", timeout=1
                ).close()
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("Browser did not expose CDP in time.")

        console.print(
            "\n[bold green]Browser opened.[/bold green] "
            "Please log in to X, then come back here and press [bold]Enter[/bold]."
        )
        input()

        with urllib.request.urlopen(
            f"http://localhost:{cdp_port}/json", timeout=5
        ) as r:
            pages = json.loads(r.read())

        x_page = next(
            (p for p in pages if "x.com" in p.get("url", "") and p.get("type") == "page"),
            None,
        ) or next((p for p in pages if p.get("type") == "page"), None)

        if not x_page or "webSocketDebuggerUrl" not in x_page:
            raise RuntimeError("No debuggable browser page found.")

        ws_url: str = x_page["webSocketDebuggerUrl"]
        ws_path = ws_url.split(f"localhost:{cdp_port}", 1)[1]

        sock = _cdp_ws_connect("localhost", cdp_port, ws_path)
        try:
            cmd = json.dumps({
                "id": 1,
                "method": "Network.getCookies",
                "params": {"urls": ["https://x.com", "https://twitter.com"]},
            })
            _cdp_ws_send(sock, cmd)
            response = json.loads(_cdp_ws_recv(sock))
        finally:
            sock.close()

        cookies = {
            c["name"]: c["value"]
            for c in response.get("result", {}).get("cookies", [])
        }

        auth_token = cookies.get("auth_token")
        ct0 = cookies.get("ct0")

        if not auth_token or not ct0:
            found = list(cookies.keys())
            raise RuntimeError(
                f"Could not find auth_token/ct0. "
                f"Found cookies: {found}\n"
                "Make sure you are fully logged in before pressing Enter."
            )

        return {"auth_token": auth_token, "ct0": ct0}

    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        shutil.rmtree(user_data_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

@click.command("config")
@click.option("--login", is_flag=True, default=False,
              help="Auto-capture auth_token & ct0 by opening browser (Chrome/Edge required)")
@click.option("--auth-token", required=False, default=None, help="auth_token cookie from your browser")
@click.option("--ct0", required=False, default=None, help="ct0 cookie from your browser")
@click.option("--output", default=None, help="Default download directory")
@click.option(
    "--concurrency", default=None, type=int,
    help="Concurrent download threads (default: 5)"
)
@click.option("--bearer-token", default=None, help="Override the X web app bearer token")
@click.option(
    "--proxy", default=None,
    help='Proxy URL, e.g. "http://127.0.0.1:7890" or "socks5://127.0.0.1:1080"'
)
@click.option(
    "--query-id", "query_ids_raw", multiple=True,
    metavar="NAME=ID",
    help=(
        "Update a GraphQL query ID. Can be repeated.\n"
        "Names: UserByScreenName, UserTweets, Likes\n"
        'Example: --query-id "UserByScreenName=abc123"'
    ),
)
def cmd_config(
    login: bool,
    auth_token: Optional[str],
    ct0: Optional[str],
    output: Optional[str],
    concurrency: Optional[int],
    bearer_token: Optional[str],
    proxy: Optional[str],
    query_ids_raw: tuple,
) -> None:
    """Save credentials and settings to ~/.x-downloader/config.json."""
    cfg = load_config()

    if login:
        try:
            captured = _capture_auth_via_cdp()
            auth_token = captured["auth_token"]
            ct0 = captured["ct0"]
            console.print("[green]✓ auth_token and ct0 captured successfully.[/green]")
        except RuntimeError as exc:
            console.print(f"[bold red]Login capture failed:[/bold red] {exc}")
            raise SystemExit(1)

    if auth_token:
        cfg["auth_token"] = auth_token
    if ct0:
        cfg["ct0"] = ct0
    if output:
        cfg["output_dir"] = output
    if concurrency is not None:
        cfg["concurrency"] = concurrency
    if bearer_token:
        cfg["bearer_token"] = bearer_token
    if proxy is not None:
        cfg["proxy"] = proxy
    if query_ids_raw:
        qids = cfg.get("query_ids", {})
        for item in query_ids_raw:
            if "=" in item:
                name, qid = item.split("=", 1)
                qids[name.strip()] = qid.strip()
                console.print(f"[green]✓ Query ID updated:[/green] {name.strip()} = {qid.strip()}")
            else:
                console.print(f"[yellow]Skipping invalid --query-id (expected NAME=ID): {item}[/yellow]")
        cfg["query_ids"] = qids
    save_config(cfg)
    console.print(
        f"[green]✓ Config saved![/green]\n"
        f"Config path: [dim]{get_config_path()}[/dim]"
    )
