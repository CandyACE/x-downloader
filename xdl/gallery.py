"""Generate a single-file HTML gallery from the download output directory."""

from __future__ import annotations

import html
import os
import re
from importlib import resources
from pathlib import Path
from urllib.parse import quote as _url_quote

from rich.console import Console

console = Console()


def _read_static(name: str) -> str:
    """Read a bundled frontend asset from ``xdl/static/``."""
    return (resources.files("xdl") / "static" / name).read_text(encoding="utf-8")

_IMAGE_EXTS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
_VIDEO_EXTS = frozenset({".mp4"})
_SKIP_NAMES = frozenset({"index.html"})


def _parse_folder_name(name: str) -> tuple[str, str, str]:
    """
    Parse '{full_name}_{screen_name}_{user_id}' folder name.

    Returns (display_name, screen_name, user_id).
    Falls back gracefully if the format doesn't match.
    """
    parts = name.split("_")
    # user_id is the last all-digit segment
    if len(parts) >= 3 and parts[-1].isdigit():
        user_id = parts[-1]
        screen_name = parts[-2]
        display_name = "_".join(parts[:-2]) or screen_name
        return display_name, screen_name, user_id
    # Fallback: treat the whole folder name as display_name
    return name, name, ""


def _collect_media_files(folder: Path) -> list[tuple[str, str]]:
    """
    Return a sorted list of (relative_filename, media_type) for a user folder.

    media_type is 'image' or 'video'.
    """
    results: list[tuple[str, str]] = []
    for entry in sorted(folder.iterdir()):
        if not entry.is_file():
            continue
        if entry.name in _SKIP_NAMES or entry.name.startswith("."):
            continue
        ext = entry.suffix.lower()
        if ext in _IMAGE_EXTS:
            results.append((entry.name, "image"))
        elif ext in _VIDEO_EXTS:
            results.append((entry.name, "video"))
    return results


def _scan_output_dir(output_dir: Path) -> list[dict]:
    """Scan output_dir and return a list of user dicts, sorted by folder name."""
    users = []
    for folder in sorted(output_dir.iterdir()):
        if not folder.is_dir():
            continue
        if folder.name.startswith(".") or folder.name == "__pycache__":
            continue
        files = _collect_media_files(folder)
        if not files:
            continue
        display_name, screen_name, user_id = _parse_folder_name(folder.name)
        users.append(
            {
                "folder_name": folder.name,
                "display_name": display_name,
                "screen_name": screen_name,
                "user_id": user_id,
                "files": files,  # list of (filename, media_type)
            }
        )
    return users


def _media_thumb_html(
    folder_name: str, filename: str, media_type: str, *, lazy: bool = False
) -> str:
    """Return an <img> or <video> HTML snippet for a thumbnail."""
    safe_path = _url_quote(folder_name, safe="") + "/" + _url_quote(filename, safe="")
    if media_type == "video":
        return (
            f'<video src="{safe_path}" autoplay loop muted playsinline '
            f'class="thumb-video"></video>'
        )
    loading = ' loading="lazy"' if lazy else ""
    alt = html.escape(filename)
    return f'<img src="{safe_path}" alt="{alt}"{loading} class="thumb-img">'


def _render_index(users: list[dict], output_dir: Path, media_base: str = "") -> None:
    """Render the single-file index.html gallery into output_dir."""
    out = output_dir / "index.html"
    out.write_text(build_gallery_html(users, media_base=media_base), encoding="utf-8")


def _snowflake_ms(tweet_id: str) -> int:
    """Decode a Twitter/X snowflake ID to a millisecond epoch timestamp."""
    try:
        return (int(tweet_id) >> 22) + 1288834974657
    except (ValueError, TypeError):
        return 0


def build_gallery_html(users: list[dict], *, media_base: str = "", thumb_base: str = "", api_mode: bool = False) -> str:
    """
    Build and return the complete gallery HTML string.

    *users* is a list of dicts with keys:
      folder_name, display_name, screen_name, user_id, files
      where files is a list of (filename, media_type),
      (filename, media_type, tweet_id), or
      (filename, media_type, tweet_id, has_thumb) tuples.

    Pass an empty list with ``api_mode=True`` for the SPA lazy-loading mode.

    *media_base*:
      - "" (default)  → folder mode: image URLs are ``{folder}/{filename}``
      - "/media"      → serve mode:  image URLs are ``/media/{uid}/{filename}``

    *thumb_base*:
      - "" (default)  → no thumbnails (folder mode)
      - "/thumb"      → serve mode: thumbnail URLs are ``/thumb/{uid}/{filename}``

    *api_mode*:
      - False (default) → all user/file data embedded inline in the HTML
      - True            → SPA mode: JS fetches /api/users and /api/media/{uid} lazily
    """
    total_media = 0 if api_mode else sum(len(u["files"]) for u in users)
    api_mode_js = "true" if api_mode else "false"
    meta_text = "加载中…" if api_mode else f"{len(users)} 位用户 · {total_media} 张媒体"

    if api_mode:
        user_data_js = "let USERS = [];"
    else:
        # ── Build per-user data blocks for JS ──────────────────────────────────
        user_data_js_parts: list[str] = []
        for u in users:
            parts: list[str] = []
            for row in u["files"]:
                fn, mt = row[0], row[1]
                tweet_id = row[2] if len(row) > 2 else ""
                has_thumb = bool(row[3]) if len(row) > 3 else False
                t_norm = 'video' if mt in ('video', 'animated_gif') else 'image'
                ts = _snowflake_ms(tweet_id) if tweet_id else 0
                ts_part = f",ts:{ts}" if ts else ""
                tid_part = f",tid:{json_str(tweet_id)}" if tweet_id else ""
                ht_part = ",ht:1" if has_thumb else ""
                parts.append(f"{{f:{json_str(fn)},t:{json_str(t_norm)}{ts_part}{tid_part}{ht_part}}}")
            files_js = ", ".join(parts)
            user_data_js_parts.append(
                f'{{folder:{json_str(u["folder_name"])},'
                f'display:{json_str(u["display_name"])},'
                f'screen:{json_str(u["screen_name"])},'
                f'uid:{json_str(u["user_id"])},'
                f"files:[{files_js}]}}"
            )
        user_data_js_sep = ",\n  "
        user_data_js = f"const USERS = [\n  {user_data_js_sep.join(user_data_js_parts)}\n];"

    config_js = '\n'.join((
        user_data_js,
        f"const _API_MODE = {api_mode_js};",
        f"const _MEDIA_BASE = {json_str(media_base)};",
        f"const _THUMB_BASE = {json_str(thumb_base)};",
    ))
    _repl = {
        "__GALLERY_CSS__": _read_static("gallery.css"),
        "__CONFIG_JS__": config_js,
        "__GALLERY_JS__": _read_static("gallery.js"),
        "__META_TEXT__": meta_text,
    }
    template = _read_static("gallery.html")
    html_content = re.sub(
        "|".join(re.escape(k) for k in _repl),
        lambda m: _repl[m.group(0)],
        template,
    )
    return html_content


def json_str(s: str) -> str:
    """Minimal JSON-string encoding for embedding in JS."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def generate_gallery(output_dir: Path) -> None:
    """
    Scan *output_dir* for user subfolders and generate a single index.html gallery.

    Prints the output path on success. Silently skips if no user folders found.
    """
    output_dir = Path(output_dir)
    users = _scan_output_dir(output_dir)
    if not users:
        console.print(
            "[yellow]Gallery: no user folders found in output dir, skipping.[/yellow]"
        )
        return

    _render_index(users, output_dir)
    total = sum(len(u["files"]) for u in users)
    index_path = output_dir / "index.html"
    console.print(
        f"[green]✓ Gallery generated:[/green] {index_path}\n"
        f"  [dim]{len(users)} users · {total} media files[/dim]"
    )
