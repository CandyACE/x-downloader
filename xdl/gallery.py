"""Generate a single-file HTML gallery from the download output directory."""

from __future__ import annotations

import html
import os
from pathlib import Path
from urllib.parse import quote as _url_quote

from rich.console import Console

console = Console()

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

    html_content = f"""\
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>X Gallery</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#000;color:#e7e9ea;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;min-height:100vh}}

/* ── Top bar ── */
.topbar{{display:flex;align-items:center;gap:12px;padding:12px 20px;border-bottom:1px solid #2f3336;position:sticky;top:0;background:#000;z-index:10}}
.topbar h1{{font-size:18px;font-weight:700}}
.topbar .meta{{color:#71767b;font-size:14px;margin-left:auto}}
.back-btn{{display:none;align-items:center;gap:6px;background:none;border:1px solid #536471;color:#e7e9ea;padding:6px 14px;border-radius:20px;cursor:pointer;font-size:14px}}
.back-btn:hover{{background:#1d1f23}}

/* ── Cards grid ── */
#view-cards{{padding:20px}}
.cards-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:16px}}
.card{{background:#16181c;border:1px solid #2f3336;border-radius:12px;overflow:hidden;cursor:pointer;transition:border-color .2s}}
.card:hover{{border-color:#536471}}
.card-thumbs{{display:grid;grid-template-columns:repeat(3,1fr);gap:2px;aspect-ratio:3/2;overflow:hidden;background:#000}}
.card-thumbs .thumb-img,.card-thumbs .thumb-video{{width:100%;height:100%;object-fit:cover;display:block}}
/* Fill card when fewer than 3 thumbnails */
.card-thumbs:not(:has(>:nth-child(2))){{grid-template-columns:1fr}}
.card-thumbs:has(>:nth-child(2):last-child){{grid-template-columns:repeat(2,1fr)}}
.card-thumbs:has(>:nth-child(4):last-child){{grid-template-columns:repeat(2,1fr)}}
.card-thumbs:has(>:nth-child(5):last-child){{grid-template-columns:repeat(6,1fr)}}
.card-thumbs:has(>:nth-child(5):last-child)>*{{grid-column:span 2}}
.card-thumbs:has(>:nth-child(5):last-child)>:nth-child(4),.card-thumbs:has(>:nth-child(5):last-child)>:nth-child(5){{grid-column:span 3}}
.card-info{{padding:10px 12px;display:flex;align-items:center;gap:8px}}
.card-info-text{{display:flex;flex-direction:column;gap:2px;flex:1;min-width:0}}
.card-name{{font-weight:700;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.card-handle{{color:#71767b;font-size:13px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.card-count{{flex-shrink:0;color:#71767b;font-size:13px;background:#2f3336;padding:2px 8px;border-radius:10px}}
.search-box{{background:#16181c;border:1px solid #536471;color:#e7e9ea;padding:6px 14px;border-radius:20px;font-size:14px;outline:none;width:220px;transition:border-color .2s}}
.search-box:focus{{border-color:#1d9bf0}}
.search-box::placeholder{{color:#536471}}
.filter-tabs{{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap;align-items:center}}
.ft{{background:none;border:1px solid #536471;color:#71767b;padding:4px 14px;border-radius:20px;cursor:pointer;font-size:13px;transition:all .15s}}
.ft.active{{background:#e7e9ea;color:#000;border-color:#e7e9ea}}
.ft:hover:not(.active){{background:#1d1f23;color:#e7e9ea}}
.sort-divider{{color:#536471;font-size:13px;margin:0 4px}}
.st{{background:none;border:1px solid #2f3336;color:#536471;padding:4px 12px;border-radius:20px;cursor:pointer;font-size:12px;transition:all .15s}}
.st.active{{border-color:#536471;color:#e7e9ea}}
.st:hover:not(.active){{background:#1d1f23;color:#e7e9ea}}

/* ── Context menu ── */
#ctx-menu{{display:none;position:fixed;z-index:200;background:#16181c;border:1px solid #2f3336;border-radius:8px;padding:4px 0;min-width:160px;box-shadow:0 4px 16px rgba(0,0,0,.6);list-style:none;font-size:14px}}
#ctx-menu li{{padding:8px 16px;cursor:pointer;color:#e7e9ea;user-select:none}}
#ctx-menu li:hover{{background:#1d1f23}}
#ctx-menu li.danger{{color:#f4212e}}
#ctx-menu li.danger:hover{{background:#2d1113}}

/* ── Detail view ── */
#view-detail{{display:none;padding:0 20px 20px}}
.detail-header{{padding:16px 0 12px;border-bottom:1px solid #2f3336;margin-bottom:16px}}
.detail-name{{font-size:20px;font-weight:700}}
.detail-meta{{color:#71767b;font-size:14px;margin-top:2px}}
.media-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:3px}}
.media-item{{position:relative;aspect-ratio:1;overflow:hidden;background:#16181c;cursor:pointer}}
.media-item img,.media-item video{{width:100%;height:100%;object-fit:cover;display:block;transition:opacity .2s}}
.media-item:hover img,.media-item:hover video{{opacity:.85}}
.media-item-date{{position:absolute;bottom:4px;right:6px;color:#fff;font-size:11px;text-shadow:0 1px 3px rgba(0,0,0,.9);pointer-events:none;opacity:0;transition:opacity .15s}}
.media-item:hover .media-item-date{{opacity:1}}
.play-ov{{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;pointer-events:none}}
.play-ov::after{{content:'▶';font-size:24px;color:#fff;line-height:1;width:48px;height:48px;border-radius:50%;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;padding-left:4px;text-shadow:none}}

/* ── Lightbox ── */
#lightbox{{display:none;position:fixed;inset:0;background:rgba(0,0,0,.92);z-index:100;align-items:center;justify-content:center;overflow:hidden}}
#lightbox.active{{display:flex}}
#lb-media{{max-width:90vw;max-height:90vh;object-fit:contain;border-radius:4px;cursor:default;user-select:none;-webkit-user-drag:none}}
#lb-media.lb-video{{max-width:90vw;max-height:90vh;cursor:default;transition:none}}
.lb-btn{{position:fixed;top:50%;transform:translateY(-50%);background:rgba(255,255,255,.1);border:none;color:#fff;font-size:28px;padding:10px 16px;cursor:pointer;border-radius:6px;z-index:101;transition:background .2s}}
.lb-btn:hover{{background:rgba(255,255,255,.2)}}
#lb-prev{{left:12px}}
#lb-next{{right:12px}}
#lb-close{{position:fixed;top:12px;right:16px;background:rgba(255,255,255,.1);border:none;color:#fff;font-size:22px;padding:6px 12px;cursor:pointer;border-radius:6px;z-index:101}}
#lb-counter{{position:fixed;bottom:16px;left:50%;transform:translateX(-50%);color:#71767b;font-size:13px}}
#lb-tweet{{position:fixed;bottom:16px;right:80px;background:rgba(255,255,255,.1);color:#fff;font-size:13px;padding:6px 14px;border-radius:20px;text-decoration:none;z-index:101;display:none}}
#lb-tweet:hover{{background:rgba(255,255,255,.2)}}
.handle-link{{color:#1d9bf0;text-decoration:none}}
.handle-link:hover{{text-decoration:underline}}

/* ── Dynamic Island Toast ── */
#toast{{position:fixed;top:16px;left:50%;z-index:300;transform:translateX(-50%) translateY(-200px) scale(0.5);opacity:0;pointer-events:none;transition:transform 0.5s cubic-bezier(0.34,1.56,0.64,1),opacity 0.3s ease}}
#toast.toast-in{{transform:translateX(-50%) translateY(0) scale(1);opacity:1;pointer-events:auto}}
#toast-box{{background:#1c1c1e;border-radius:20px;overflow:hidden;box-shadow:0 12px 40px rgba(0,0,0,.8),0 0 0 1px rgba(255,255,255,.08);min-width:330px;max-width:min(30vw,600px)}}
#toast-card{{display:none;flex-direction:column}}
#toast-card-thumb{{width:100%;aspect-ratio:16/9;background:#2c2c2e;display:grid;grid-template-columns:1fr 1fr;gap:2px;overflow:hidden}}
#toast-card-thumb.single{{grid-template-columns:1fr}}
#toast-card-thumb.three{{grid-template-columns:1fr 1fr 1fr}}
#toast-card-thumb img,#toast-card-thumb video{{width:100%;height:100%;object-fit:cover;display:block}}
#toast-card-body{{padding:12px 14px 6px;color:#8e8e93;font-size:13px;line-height:1.5}}
#toast-card-btns{{display:flex;gap:8px;padding:10px 14px 14px}}
#toast-cancel-btn,#toast-delete-btn{{flex:1;border:none;border-radius:14px;padding:10px;font-size:14px;font-weight:600;cursor:pointer}}
#toast-cancel-btn{{background:#2c2c2e;color:#e7e9ea}}
#toast-cancel-btn:hover{{background:#3a3a3c}}
#toast-delete-btn{{background:#f4212e;color:#fff}}
#toast-delete-btn:hover{{background:#d9001b}}
#toast-pill{{display:none;align-items:center;gap:12px;padding:10px 14px 10px 10px;overflow:hidden;position:relative}}
#toast-thumb{{width:44px;height:44px;border-radius:10px;overflow:hidden;flex-shrink:0;background:#2c2c2e}}
#toast-thumb img,#toast-thumb video{{width:100%;height:100%;object-fit:cover;display:block}}
#toast-body{{display:flex;flex-direction:column;gap:2px;min-width:0;flex:1}}
#toast-label{{color:#8e8e93;font-size:11px}}
#toast-msg{{color:#f2f2f7;font-size:13px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:180px}}
#toast-undo{{background:rgba(10,132,255,.15);color:#0a84ff;border:none;border-radius:16px;padding:6px 14px;font-size:13px;font-weight:600;cursor:pointer;flex-shrink:0;white-space:nowrap}}
#toast-undo:hover{{background:rgba(10,132,255,.28)}}
#toast-track{{position:absolute;bottom:0;left:0;right:0;height:2px;background:rgba(255,255,255,.06)}}
#toast-bar{{height:100%;width:100%;background:#0a84ff;transform-origin:left center;border-radius:1px}}
/* ── User card multi-select ── */
.card{{position:relative}}
.card .card-sel-check{{display:none;position:absolute;top:8px;right:8px;width:22px;height:22px;border-radius:50%;background:rgba(0,0,0,.55);border:2px solid rgba(255,255,255,.6);z-index:10;align-items:center;justify-content:center;pointer-events:none;font-size:12px;font-weight:700;color:#fff;transition:background .12s,border-color .12s}}
#view-cards.user-sel-mode .card .card-sel-check{{display:flex}}
.card.card-selected .card-sel-check{{background:#0a84ff;border-color:#0a84ff}}
.card.card-selected{{outline:3px solid #0a84ff;outline-offset:-2px}}
#view-cards.user-sel-mode .card{{cursor:default}}
/* ── Multi-select ── */
.media-item .sel-check{{display:none;position:absolute;top:8px;right:8px;width:22px;height:22px;border-radius:50%;background:rgba(0,0,0,.55);border:2px solid rgba(255,255,255,.6);z-index:2;align-items:center;justify-content:center;pointer-events:none;font-size:12px;font-weight:700;color:#fff;transition:background .12s,border-color .12s}}
.sel-mode .media-item .sel-check{{display:flex}}
.media-item.sel-active .sel-check{{background:#0a84ff;border-color:#0a84ff}}
.media-item.sel-active::after{{content:'';position:absolute;inset:0;border:3px solid #0a84ff;pointer-events:none;z-index:1}}
#sel-bar{{display:none;position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:#1c1c1e;border:1px solid rgba(255,255,255,.12);border-radius:20px;padding:10px 10px 10px 16px;box-shadow:0 8px 28px rgba(0,0,0,.75);z-index:150;align-items:center;gap:12px;white-space:nowrap}}
#sel-bar.active{{display:flex}}
#sel-count{{color:#e7e9ea;font-size:14px;font-weight:600}}
#sel-del-btn{{background:#f4212e;color:#fff;border:none;border-radius:14px;padding:8px 20px;font-size:14px;font-weight:600;cursor:pointer;transition:background .15s}}
#sel-del-btn:hover:not(:disabled){{background:#d9001b}}
#sel-del-btn:disabled{{opacity:.45;cursor:default}}
/* ── Page loading overlay ── */
#page-loading{{position:fixed;inset:0;z-index:9999;background:#000;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px;transition:opacity .35s ease}}
#page-loading.fade-out{{opacity:0;pointer-events:none}}
.pl-spinner{{width:42px;height:42px;border:3px solid rgba(255,255,255,.12);border-top-color:#1d9bf0;border-radius:50%;animation:pl-spin .8s linear infinite}}
@keyframes pl-spin{{to{{transform:rotate(360deg)}}}}
.pl-text{{color:#71767b;font-size:14px;letter-spacing:.3px}}
</style>
</head>
<body>

<div id="page-loading">
  <div class="pl-spinner"></div>
  <span class="pl-text" id="pl-text">正在加载…</span>
</div>

<div class="topbar">
  <button class="back-btn" id="back-btn" onclick="history.back()">← 返回</button>
  <h1 id="topbar-title">X Gallery</h1>
  <input type="search" id="search-input" class="search-box" placeholder="搜索用户…" oninput="onSearch(this.value)">
  <span id="ust-wrap" style="display:none;align-items:center;gap:6px;margin-left:8px">
    <span class="sort-divider">排序</span>
    <button class="st active" id="ust-name" onclick="setUserSort('name')">名称</button>
    <button class="st" id="ust-count" onclick="setUserSort('count')">数量</button>
    <button class="st ust-recent" id="ust-recent" onclick="setUserSort('recent')">最近</button>
    <span class="sort-divider">|</span>
    <button class="ft" id="user-sel-toggle" onclick="toggleUserSelMode()">多选</button>
  </span>
  <span class="meta" id="topbar-meta">{meta_text}</span>
</div>

<div id="view-cards">
  <div id="vs-host"></div>
</div>

<div id="view-detail">
  <div class="detail-header">
    <div class="detail-name" id="detail-name"></div>
    <div class="detail-meta" id="detail-meta"></div>
    <div class="filter-tabs" id="filter-tabs">
      <button class="ft active" data-f="all" onclick="setFilter('all')">全部</button>
      <button class="ft" data-f="image" onclick="setFilter('image')">图片</button>
      <button class="ft" data-f="video" onclick="setFilter('video')">视频</button>
      <span class="sort-divider">|</span>
      <button class="st active" data-s="default" onclick="setSort('default')">默认</button>
      <button class="st" data-s="desc" onclick="setSort('desc')">最新</button>
      <button class="st" data-s="asc" onclick="setSort('asc')">最早</button>
      <span class="sort-divider">|</span>
      <button class="ft" id="sel-toggle" onclick="toggleSelMode()">多选</button>
    </div>
  </div>
  <div class="media-grid" id="media-grid"></div>
</div>

<!-- Context menu -->
<ul id="ctx-menu"></ul>

<!-- Toast (Dynamic Island) -->
<div id="toast">
  <div id="toast-box">
    <div id="toast-card">
      <div id="toast-card-thumb"></div>
      <div id="toast-card-body"></div>
      <div id="toast-card-btns">
        <button id="toast-cancel-btn">取消</button>
        <button id="toast-delete-btn">删除</button>
      </div>
    </div>
    <div id="toast-pill">
      <div id="toast-thumb"></div>
      <div id="toast-body">
        <span id="toast-label"></span>
        <span id="toast-msg"></span>
      </div>
      <button id="toast-undo">撤销</button>
      <div id="toast-track"><div id="toast-bar"></div></div>
    </div>
  </div>
</div>

<!-- Multi-select action bar -->
<div id="sel-bar">
  <span id="sel-count">已选 0 项</span>
  <button id="sel-del-btn" onclick="deleteSelectedDispatch()" disabled>删除选中</button>
</div>

<!-- Lightbox -->
<div id="lightbox" onclick="lbClose()">
  <button class="lb-btn" id="lb-prev" onclick="event.stopPropagation();lbNav(-1)">&#8249;</button>
  <img id="lb-media" src="" alt="">
  <button class="lb-btn" id="lb-next" onclick="event.stopPropagation();lbNav(1)">&#8250;</button>
  <button id="lb-close" onclick="lbClose()">&#x2715;</button>
  <div id="lb-counter"></div>
  <a id="lb-tweet" href="#" target="_blank" rel="noopener" onclick="event.stopPropagation()">查看推文 ↗</a>
</div>

<script>
{user_data_js}
const _API_MODE = {api_mode_js};
const _MEDIA_BASE = {json_str(media_base)};
const _THUMB_BASE = {json_str(thumb_base)};

function _countFiles(u) {{
  if (!_API_MODE) return u.files.length;
  return u.filesLoaded ? u.files.length : (u.count || 0);
}}

function _mpath(u, f) {{
  return _MEDIA_BASE
    ? (_MEDIA_BASE + '/' + encodeURIComponent(u.uid) + '/' + encodeURIComponent(f))
    : (encodeURIComponent(u.folder) + '/' + encodeURIComponent(f));
}}

function _tpath(u, f) {{
  return _THUMB_BASE + '/' + encodeURIComponent(u.uid) + '/' + encodeURIComponent(f);
}}

function _fmtDate(ts) {{
  var d = new Date(ts);
  return d.getFullYear() + '-'
    + String(d.getMonth()+1).padStart(2,'0') + '-'
    + String(d.getDate()).padStart(2,'0');
}}

let currentUser = null;
let lbFiles = [];
let lbIdx = 0;
let _cardListScrollY = 0;

/* ── Page loading overlay ── */
function _showPageLoading(text) {{
  var el = document.getElementById('page-loading');
  var txt = document.getElementById('pl-text');
  if (txt && text) txt.textContent = text;
  if (el) {{ el.classList.remove('fade-out'); el.style.display = 'flex'; }}
}}
function _hidePageLoading() {{
  var el = document.getElementById('page-loading');
  if (!el) return;
  el.classList.add('fade-out');
  setTimeout(function() {{ el.style.display = 'none'; }}, 380);
}}

/* ── Context menu ── */
function _showCtxMenu(e, items) {{
  e.preventDefault();
  e.stopPropagation();
  var menu = document.getElementById('ctx-menu');
  menu.innerHTML = '';
  items.forEach(function(item) {{
    var li = document.createElement('li');
    if (item.danger) li.className = 'danger';
    li.textContent = item.label;
    li.onclick = function(ev) {{ ev.stopPropagation(); _hideCtxMenu(); item.action(); }};
    menu.appendChild(li);
  }});
  menu.style.display = 'block';
  var x = e.clientX, y = e.clientY;
  var mw = menu.offsetWidth, mh = menu.offsetHeight;
  if (x + mw > window.innerWidth) x = window.innerWidth - mw - 4;
  if (y + mh > window.innerHeight) y = window.innerHeight - mh - 4;
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
}}
function _hideCtxMenu() {{
  document.getElementById('ctx-menu').style.display = 'none';
}}
document.addEventListener('click', _hideCtxMenu);
document.addEventListener('contextmenu', function(e) {{
  if (!e.target.closest('#ctx-menu')) _hideCtxMenu();
}});
document.addEventListener('keydown', function(e) {{
  if (e.key === 'Escape') _hideCtxMenu();
}});

/* ── Toast (Dynamic Island) ── */
var _toastTimer = null;
var _toastCommit = null;

function _confirmDelete(onConfirm) {{
  if (_toastTimer) {{
    clearTimeout(_toastTimer); _toastTimer = null;
    if (_toastCommit) {{ _toastCommit(); _toastCommit = null; }}
  }}
  var toast = document.getElementById('toast');
  var box = document.getElementById('toast-box');
  var cardEl = document.getElementById('toast-card');
  var pillEl = document.getElementById('toast-pill');
  toast.classList.remove('toast-in');
  box.style.transition = 'none';
  box.style.height = ''; box.style.borderRadius = '20px';
  cardEl.style.opacity = '1'; cardEl.style.pointerEvents = ''; cardEl.style.display = 'flex';
  pillEl.style.display = 'none'; pillEl.style.opacity = '1';
  toast.style.transition = ''; toast.style.transform = ''; toast.style.opacity = '';
  void toast.offsetWidth;
  document.getElementById('toast-delete-btn').onclick = function() {{ onConfirm(); }};
  document.getElementById('toast-cancel-btn').onclick = function() {{ _hideToast(); }};
  toast.classList.add('toast-in');
}}

function _toUndo(thumbHtml, label, msg, onUndo, onCommit) {{
  document.getElementById('toast-thumb').innerHTML = thumbHtml;
  document.getElementById('toast-label').textContent = label;
  document.getElementById('toast-msg').textContent = msg;
  document.getElementById('toast-undo').onclick = function() {{
    clearTimeout(_toastTimer); _toastTimer = null; _toastCommit = null;
    _hideToast(); onUndo();
  }};
  var box = document.getElementById('toast-box');
  var cardEl = document.getElementById('toast-card');
  var pillEl = document.getElementById('toast-pill');
  var startH = box.offsetHeight;
  box.style.height = startH + 'px';
  cardEl.style.transition = 'opacity 0.12s ease-out';
  cardEl.style.opacity = '0';
  cardEl.style.pointerEvents = 'none';
  setTimeout(function() {{
    pillEl.style.visibility = 'hidden'; pillEl.style.display = 'flex';
    var targetH = pillEl.offsetHeight;
    pillEl.style.display = 'none'; pillEl.style.visibility = '';
    cardEl.style.display = 'none';
    pillEl.style.display = 'flex'; pillEl.style.opacity = '0';
    box.style.transition = 'height 0.38s cubic-bezier(0.34,1.56,0.64,1), border-radius 0.3s ease';
    box.style.height = targetH + 'px';
    box.style.borderRadius = '28px';
    setTimeout(function() {{
      pillEl.style.transition = 'opacity 0.18s ease-in';
      pillEl.style.opacity = '1';
    }}, 180);
    var bar = document.getElementById('toast-bar');
    bar.style.transition = 'none'; bar.style.transform = 'scaleX(1)';
    requestAnimationFrame(function() {{
      requestAnimationFrame(function() {{
        bar.style.transition = 'transform 5s linear';
        bar.style.transform = 'scaleX(0)';
      }});
    }});
    _toastCommit = onCommit;
    _toastTimer = setTimeout(function() {{
      _toastTimer = null; _toastCommit = null;
      _hideToast(); onCommit();
    }}, 5000);
  }}, 120);
}}

function _hideToast() {{
  if (_toastTimer) {{
    clearTimeout(_toastTimer); _toastTimer = null;
    if (_toastCommit) {{ _toastCommit(); _toastCommit = null; }}
  }}
  var toast = document.getElementById('toast');
  toast.style.transition = 'transform 0.3s ease-in, opacity 0.25s ease-in';
  toast.style.transform = 'translateX(-50%) translateY(-80px) scale(0.85)';
  toast.style.opacity = '0';
  setTimeout(function() {{
    toast.classList.remove('toast-in');
    toast.style.transition = ''; toast.style.transform = ''; toast.style.opacity = '';
  }}, 300);
}}

function _cardThumbsHtml(u) {{
  return (u.files || u.preview || []).slice(0, 4).map(function(f) {{
    if (_THUMB_BASE && f.ht) return '<img src="' + _tpath(u, f.f) + '" loading="lazy">';
    if (f.t === 'video') return '<video src="' + _mpath(u, f.f) + '" muted playsinline preload="metadata"></video>';
    return '<img src="' + _mpath(u, f.f) + '" loading="lazy">';
  }}).join('');
}}

function _thumbHtml(u, item) {{
  if (!item) return '';
  if (item.t === 'image') return '<img src="' + _mpath(u, item.f) + '" loading="lazy">';
  var src = (_THUMB_BASE && item.ht) ? _tpath(u, item.f) : _mpath(u, item.f);
  if (_THUMB_BASE && item.ht) return '<img src="' + src + '" loading="lazy">';
  return '<video src="' + src + '" muted playsinline preload="metadata"></video>';
}}

function _updateTopbarMeta() {{
  document.getElementById('topbar-meta').textContent =
    _visibleUsers.length + ' 位用户 · ' +
    _visibleUsers.reduce(function(s,u){{return s+_countFiles(u);}},0) + ' 张媒体';
}}

function _deleteUser(u) {{
  var count = _countFiles(u);
  var thumbEl = document.getElementById('toast-card-thumb');
  var n = Math.min(count, 4);
  thumbEl.className = n === 1 ? 'single' : n === 3 ? 'three' : '';
  thumbEl.innerHTML = _cardThumbsHtml(u);
  document.getElementById('toast-card-body').innerHTML =
    '删除 <b style="color:#f2f2f7">@' + _hesc(u.screen || u.uid) + '</b> 及其全部 ' + count + ' 个媒体？';
  _confirmDelete(function() {{
    var gi = USERS.indexOf(u), vi = _visibleUsers.indexOf(u);
    if (gi >= 0) USERS.splice(gi, 1);
    if (vi >= 0) _visibleUsers.splice(vi, 1);
    _vsCache = {{}}; _vs.start = -1; _vs.end = -1;
    _vsRefresh(); _updateTopbarMeta();
    _toUndo(
      _thumbHtml(u, (u.files || u.preview || [])[0]),
      '已删除用户',
      '@' + (u.screen || u.uid),
      function() {{
        if (gi >= 0) USERS.splice(gi, 0, u);
        if (vi >= 0) _visibleUsers.splice(vi, 0, u);
        _vsCache = {{}}; _vs.start = -1; _vs.end = -1;
        _vsRefresh(); _updateTopbarMeta();
      }},
      function() {{
        fetch('/api/user/' + encodeURIComponent(u.uid), {{method:'DELETE'}})
          .catch(function() {{ alert('删除失败，请刷新页面'); }});
      }}
    );
  }});
}}

function _deleteMedia(u, item) {{
  var thumbEl = document.getElementById('toast-card-thumb');
  thumbEl.className = 'single';
  thumbEl.innerHTML = _thumbHtml(u, item);
  document.getElementById('toast-card-body').textContent =
    '删除此' + (item.t === 'video' ? '视频' : '图片') + '？';
  _confirmDelete(function() {{
    var i = u.files.indexOf(item);
    if (i >= 0) u.files.splice(i, 1);
    _renderDetailGrid();
    _toUndo(
      _thumbHtml(u, item),
      '已删除媒体',
      item.f,
      function() {{
        if (i >= 0) u.files.splice(i, 0, item); else u.files.push(item);
        _renderDetailGrid();
      }},
      function() {{
        fetch('/api/media/' + encodeURIComponent(u.uid) + '/' + encodeURIComponent(item.f), {{method:'DELETE'}})
          .catch(function() {{ alert('删除失败，请刷新页面'); }});
      }}
    );
  }});
}}

function _exitSelMode() {{
  if (!_selMode) return;
  _selMode = false;
  _selSet.clear();
  var btn = document.getElementById('sel-toggle');
  if (btn) {{ btn.textContent = '多选'; btn.classList.remove('active'); }}
  document.getElementById('sel-bar').classList.remove('active');
  var grid = document.getElementById('media-grid');
  if (grid) {{
    grid.classList.remove('sel-mode');
    _mgVS.cache.forEach(function(div) {{
      div.classList.remove('sel-active');
      var ck = div.querySelector('.sel-check');
      if (ck) ck.textContent = '';
    }});
  }}
}}

function toggleSelMode() {{
  _selMode = !_selMode;
  _selSet.clear();
  var btn = document.getElementById('sel-toggle');
  btn.textContent = _selMode ? '取消' : '多选';
  btn.classList.toggle('active', _selMode);
  var grid = document.getElementById('media-grid');
  if (grid) {{
    grid.classList.toggle('sel-mode', _selMode);
    _mgVS.cache.forEach(function(div) {{
      div.classList.remove('sel-active');
      var ck = div.querySelector('.sel-check');
      if (ck) ck.textContent = '';
    }});
  }}
  _updateSelBar();
}}

function _updateSelBar() {{
  var n = _selSet.size;
  document.getElementById('sel-count').textContent = '已选 ' + n + ' 项';
  document.getElementById('sel-del-btn').disabled = n === 0;
  document.getElementById('sel-bar').classList.toggle('active', _selMode);
}}

function _deleteSelected() {{
  var n = _selSet.size;
  if (n === 0) return;
  var u = currentUser;
  var selItems = (u.files || []).filter(function(item) {{ return _selSet.has(item.f); }});
  var thumbEl = document.getElementById('toast-card-thumb');
  var cnt = Math.min(n, 4);
  thumbEl.className = cnt === 1 ? 'single' : cnt === 3 ? 'three' : '';
  thumbEl.innerHTML = selItems.slice(0, 4).map(function(item) {{ return _thumbHtml(u, item); }}).join('');
  document.getElementById('toast-card-body').innerHTML =
    '删除已选 <b style="color:#f2f2f7">' + n + '</b> 个媒体？';
  _confirmDelete(function() {{
    var origFiles = (u.files || []).slice();
    u.files = (u.files || []).filter(function(item) {{ return !_selSet.has(item.f); }});
    var firstItem = selItems[0];
    _exitSelMode();
    _renderDetailGrid();
    _toUndo(
      firstItem ? _thumbHtml(u, firstItem) : '',
      '已删除 ' + selItems.length + ' 个媒体',
      u.screen || u.uid,
      function() {{ u.files = origFiles; _renderDetailGrid(); }},
      function() {{
        selItems.forEach(function(item) {{
          fetch('/api/media/' + encodeURIComponent(u.uid) + '/' + encodeURIComponent(item.f), {{method:'DELETE'}})
            .catch(function() {{}});
        }});
      }}
    );
  }});
}}
var _visibleUsers = USERS.slice();
var _userSort = 'name';
var _mediaFilter = 'all';
var _sortOrder = 'default';
var _selMode = false;
var _selSet = new Set();
var _userSelMode = false;
var _userSelSet = new Set();

function _buildVisibleUsers(q) {{
  var base = q ? USERS.filter(function(u) {{
    var s = (u.display + ' ' + u.screen + ' ' + u.uid).toLowerCase();
    return s.indexOf(q.toLowerCase()) >= 0;
  }}) : USERS.slice();
  if (_userSort === 'count') {{
    base.sort(function(a, b) {{ return b.count - a.count; }});
  }} else if (_userSort === 'recent') {{
    base.sort(function(a, b) {{ return (b.latest || '').localeCompare(a.latest || ''); }});
  }}
  return base;
}}

function setUserSort(s) {{
  _userSort = s;
  document.querySelectorAll('#ust-wrap .st').forEach(function(b) {{
    b.classList.toggle('active', b.id === 'ust-' + s);
  }});
  onSearch(document.getElementById('search-input').value || '');
}}

function setSort(s) {{
  _sortOrder = s;
  document.querySelectorAll('[data-s]').forEach(function(b) {{ b.classList.toggle('active', b.dataset.s === s); }});
  _renderDetailGrid();
}}

function _applySortFilter(files) {{
  var out = _mediaFilter === 'all' ? files.slice() : files.filter(function(item) {{ return item.t === _mediaFilter; }});
  if (_sortOrder !== 'default') {{
    out.sort(function(a, b) {{
      var ta = a.ts || 0, tb = b.ts || 0;
      return _sortOrder === 'desc' ? tb - ta : ta - tb;
    }});
  }}
  return out;
}}

function _exitUserSelMode() {{
  if (!_userSelMode) return;
  _userSelMode = false;
  _userSelSet.clear();
  Object.keys(_vsCache).forEach(function(k) {{
    var c = _vsCache[k];
    c.classList.remove('card-selected');
    var ck = c.querySelector('.card-sel-check');
    if (ck) ck.textContent = '';
  }});
  var btn = document.getElementById('user-sel-toggle');
  if (btn) {{ btn.textContent = '多选'; btn.classList.remove('active'); }}
  document.getElementById('sel-bar').classList.remove('active');
  document.getElementById('view-cards').classList.remove('user-sel-mode');
}}

function toggleUserSelMode() {{
  _userSelMode = !_userSelMode;
  _userSelSet.clear();
  Object.keys(_vsCache).forEach(function(k) {{
    var c = _vsCache[k];
    c.classList.remove('card-selected');
    var ck = c.querySelector('.card-sel-check');
    if (ck) ck.textContent = '';
  }});
  var btn = document.getElementById('user-sel-toggle');
  btn.textContent = _userSelMode ? '取消' : '多选';
  btn.classList.toggle('active', _userSelMode);
  document.getElementById('view-cards').classList.toggle('user-sel-mode', _userSelMode);
  _updateUserSelBar();
}}

function _updateUserSelBar() {{
  var n = _userSelSet.size;
  document.getElementById('sel-count').textContent = '已选 ' + n + ' 位用户';
  document.getElementById('sel-del-btn').disabled = n === 0;
  document.getElementById('sel-bar').classList.toggle('active', _userSelMode);
}}

function _deleteSelectedUsers() {{
  var n = _userSelSet.size;
  if (n === 0) return;
  var selUsers = _visibleUsers.filter(function(u) {{ return _userSelSet.has(u.uid); }});
  var thumbEl = document.getElementById('toast-card-thumb');
  var cnt = Math.min(n, 4);
  thumbEl.className = cnt === 1 ? 'single' : cnt === 3 ? 'three' : '';
  thumbEl.innerHTML = selUsers.slice(0, 4).map(function(u) {{
    var f = u.files && u.files[0];
    return f ? _thumbHtml(u, f) : '<div style="background:#2c2c2e;width:100%;height:100%"></div>';
  }}).join('');
  document.getElementById('toast-card-body').innerHTML =
    '删除已选 <b style="color:#f2f2f7">' + n + '</b> 位用户（含全部媒体）？';
  _confirmDelete(function() {{
    selUsers.forEach(function(u) {{
      var gi = USERS.indexOf(u);
      if (gi >= 0) USERS.splice(gi, 1);
    }});
    _exitUserSelMode();
    _vsCache = {{}};
    _visibleUsers = _buildVisibleUsers(document.getElementById('search-input').value || '');
    _vs.start = -1; _vs.end = -1;
    _vsRefresh();
    var firstUser = selUsers[0];
    var firstThumb = firstUser && firstUser.files && firstUser.files[0] ? _thumbHtml(firstUser, firstUser.files[0]) : '';
    _toUndo(
      firstThumb,
      '已删除 ' + selUsers.length + ' 位用户',
      selUsers.map(function(u) {{ return u.screen || u.uid; }}).join(', '),
      function() {{
        selUsers.forEach(function(u) {{ USERS.push(u); }});
        _vsCache = {{}};
        _visibleUsers = _buildVisibleUsers(document.getElementById('search-input').value || '');
        _vs.start = -1; _vs.end = -1;
        _vsRefresh();
      }},
      function() {{
        selUsers.forEach(function(u) {{
          fetch('/api/user/' + encodeURIComponent(u.uid), {{method:'DELETE'}})
            .catch(function() {{}});
        }});
      }}
    );
  }});
}}

function deleteSelectedDispatch() {{
  if (_userSelMode) _deleteSelectedUsers();
  else _deleteSelected();
}}

function showUser(idx, noHistory) {{
  _exitSelMode();
  _exitUserSelMode();
  _cardListScrollY = window.scrollY;
  currentUser = _visibleUsers[idx];
  const u = currentUser;
  if (!noHistory) {{
    history.pushState({{view:'user',uid:u.uid}}, '', '#user-' + encodeURIComponent(u.uid));
  }}
  document.getElementById('view-cards').style.display = 'none';
  document.getElementById('view-detail').style.display = 'block';
  document.getElementById('back-btn').style.display = 'flex';
  document.getElementById('search-input').style.display = 'none';
  document.getElementById('ust-wrap').style.display = 'none';
  document.getElementById('topbar-title').textContent = u.display + (u.screen ? ' @' + u.screen : '');
  document.getElementById('detail-name').textContent = u.display;
  if (window._mediaObs) {{ window._mediaObs.disconnect(); window._mediaObs = null; }}
  _mediaFilter = 'all';
  _sortOrder = 'default';
  document.querySelectorAll('.ft').forEach(function(b) {{ b.classList.toggle('active', b.dataset.f === 'all'); }});
  document.querySelectorAll('.st').forEach(function(b) {{ b.classList.toggle('active', b.dataset.s === 'default'); }});

  function _renderWithFiles() {{
    var total = u.files.length;
    document.getElementById('topbar-meta').textContent = total + ' 张媒体';
    document.getElementById('detail-meta').innerHTML =
      (u.screen ? '<a class="handle-link" href="https://x.com/' + encodeURIComponent(u.screen) + '" target="_blank" rel="noopener">@' + _hesc(u.screen) + '</a>' : '')
      + (u.uid ? ' \xb7 ID\uff1a' + _hesc(u.uid) : '') + ' \xb7 ' + total + ' \u5f20';
    var imgCount = u.files.filter(function(f){{return f.t==='image';}}).length;
    var vidCount = u.files.filter(function(f){{return f.t==='video';}}).length;
    document.querySelector('[data-f="all"]').textContent = '全部 ' + total;
    document.querySelector('[data-f="image"]').textContent = '图片 ' + imgCount;
    document.querySelector('[data-f="video"]').textContent = '视频 ' + vidCount;
    document.querySelector('[data-f="image"]').style.display = imgCount ? '' : 'none';
    document.querySelector('[data-f="video"]').style.display = vidCount ? '' : 'none';
    var hasDates = u.files.some(function(f) {{ return f.ts; }});
    document.querySelectorAll('.st,.sort-divider').forEach(function(el) {{
      el.style.display = hasDates ? '' : 'none';
    }});
    document.getElementById('filter-tabs').style.display = '';
    window.scrollTo(0, 0);
    _renderDetailGrid();
  }}

  if (_API_MODE && !u.filesLoaded) {{
    var cnt = u.count || '\u2026';
    document.getElementById('topbar-meta').textContent = cnt + ' 张媒体';
    document.getElementById('detail-meta').innerHTML =
      (u.screen ? '<a class="handle-link" href="https://x.com/' + encodeURIComponent(u.screen) + '" target="_blank" rel="noopener">@' + _hesc(u.screen) + '</a>' : '')
      + (u.uid ? ' \xb7 ID\uff1a' + _hesc(u.uid) : '') + ' \xb7 ' + cnt + ' \u5f20';
    document.getElementById('filter-tabs').style.display = 'none';
    document.getElementById('media-grid').innerHTML = '';
    if (!u._fetching) {{
      u._fetching = true;
      _showPageLoading('@' + (u.screen || u.uid) + ' 的媒体加载中…');
      fetch('/api/media/' + encodeURIComponent(u.uid))
        .then(function(r) {{
          if (!r.ok) throw new Error('HTTP ' + r.status);
          return r.json();
        }})
        .then(function(files) {{
          u.files = files;
          u.filesLoaded = true;
          u._fetching = false;
          _hidePageLoading();
          if (currentUser === u) _renderWithFiles();
        }})
        .catch(function() {{
          u._fetching = false;
          _hidePageLoading();
          if (currentUser === u) {{
            document.getElementById('media-grid').innerHTML =
              '<div style="padding:60px;text-align:center;color:#f4212e;font-size:15px">' +
              '加载失败，<a href="javascript:void(0)" onclick="showUser(' + idx + ',true)" style="color:#0a84ff">重试</a></div>';
          }}
        }});
    }}
  }} else {{
    _renderWithFiles();
  }}
}}

function showCards(noHistory) {{
  _exitSelMode();
  document.getElementById('view-detail').style.display = 'none';
  document.getElementById('view-cards').style.display = 'block';
  document.getElementById('back-btn').style.display = 'none';
  document.getElementById('search-input').style.display = '';
  document.getElementById('ust-wrap').style.display = 'flex';
  document.getElementById('topbar-title').textContent = 'X Gallery';
  // Re-apply whatever is still in the search box to keep filter in sync
  onSearch(document.getElementById('search-input').value || '');
  requestAnimationFrame(function() {{
    window.scrollTo(0, _cardListScrollY);
    _vsUpdate();
  }});
}}

function lbOpen(idx) {{
  _lbResetZoom();
  lbIdx = idx;
  lbRender();
  document.getElementById('lightbox').classList.add('active');
  document.body.style.overflow = 'hidden';
}}

function lbClose() {{
  _lbResetZoom();
  document.getElementById('lightbox').classList.remove('active');
  document.body.style.overflow = '';
  const vid = document.getElementById('lb-media');
  if (vid.tagName === 'VIDEO') {{ vid.pause(); }}
}}

function lbNav(dir) {{
  lbIdx = (lbIdx + dir + lbFiles.length) % lbFiles.length;
  lbRender();
}}

function lbRender() {{
  _lbResetZoom();
  const item = lbFiles[lbIdx];
  const path = _mpath(currentUser, item.f);
  let el = document.getElementById('lb-media');

  if (item.t === 'video') {{
    if (el.tagName !== 'VIDEO') {{
      const v = document.createElement('video');
      v.id = 'lb-media';
      v.setAttribute('controls', ''); v.setAttribute('autoplay', ''); v.setAttribute('loop', ''); v.setAttribute('muted', '');
      v.className = 'lb-video';
      el.replaceWith(v); el = v;
    }}
    el.src = path;
    el.load();
    el.play().catch(function(){{}});
  }} else {{
    if (el.tagName !== 'IMG') {{
      const img = document.createElement('img');
      img.id = 'lb-media'; img.alt = item.f;
      el.replaceWith(img); el = img;
    }}
    el.src = path; el.alt = item.f;
  }}
  _lbAttachZoom(el);
  document.getElementById('lb-counter').textContent = (lbIdx + 1) + ' / ' + lbFiles.length;
  var tlink = document.getElementById('lb-tweet');
  if (tlink) {{
    if (item.tid) {{ tlink.href = 'https://x.com/i/web/status/' + item.tid; tlink.style.display = 'inline-block'; }}
    else {{ tlink.style.display = 'none'; }}
  }}
}}

// ── Lightbox zoom / pan ─────────────────────────────────────────────────
var _lbScale = 1;
var _lbDrag = {{on:false, moved:false, sx:0, sy:0, tx:0, ty:0}};

function _lbApplyTransform(el) {{
  el.style.transform = 'translate(' + _lbDrag.tx + 'px,' + _lbDrag.ty + 'px) scale(' + _lbScale + ')';
  el.style.cursor = _lbScale > 1 ? (_lbDrag.on ? 'grabbing' : 'grab') : 'default';
}}

function _lbResetZoom() {{
  _lbScale = 1;
  _lbDrag = {{on:false, moved:false, sx:0, sy:0, tx:0, ty:0}};
  var el = document.getElementById('lb-media');
  if (el && el.tagName === 'IMG') {{
    el.style.transform = '';
    el.style.cursor = 'default';
    el.style.maxWidth = '';
    el.style.maxHeight = '';
  }}
}}

function _lbAttachZoom(el) {{
  if (el.tagName !== 'IMG') {{
    el.onclick = function(e) {{ e.stopPropagation(); }};
    return;
  }}
  el.onclick = function(e) {{ e.stopPropagation(); }};

  el.onwheel = function(e) {{
    e.preventDefault();
    e.stopPropagation();
    var factor = (e.deltaY || e.deltaX || 0) < 0 ? 1.12 : 1 / 1.12;
    var newScale = Math.min(10, Math.max(1, _lbScale * factor));
    if (newScale === _lbScale) return;
    if (newScale === 1) {{
      // snap back to origin
      _lbScale = 1;
      _lbDrag.tx = 0; _lbDrag.ty = 0;
      el.style.transition = 'transform .15s ease';
      el.style.maxWidth = ''; el.style.maxHeight = '';
      _lbApplyTransform(el);
      return;
    }}
    // zoom-to-cursor: keep the point under the mouse fixed
    var cx = window.innerWidth / 2, cy = window.innerHeight / 2;
    var ratio = newScale / _lbScale;
    _lbDrag.tx = _lbDrag.tx * ratio + (e.clientX - cx) * (1 - ratio);
    _lbDrag.ty = _lbDrag.ty * ratio + (e.clientY - cy) * (1 - ratio);
    _lbScale = newScale;
    el.style.transition = 'none';
    el.style.maxWidth = 'none'; el.style.maxHeight = 'none';
    _lbApplyTransform(el);
  }};

  el.onpointerdown = function(e) {{
    if (e.button !== 0) return;
    e.preventDefault();
    el.setPointerCapture(e.pointerId);
    _lbDrag.on = true;
    _lbDrag.moved = false;
    _lbDrag.sx = e.clientX - _lbDrag.tx;
    _lbDrag.sy = e.clientY - _lbDrag.ty;
    el.style.cursor = _lbScale > 1 ? 'grabbing' : 'default';
  }};
  el.onpointermove = function(e) {{
    if (!_lbDrag.on) return;
    var nx = e.clientX - _lbDrag.sx;
    var ny = e.clientY - _lbDrag.sy;
    if (Math.abs(nx - _lbDrag.tx) > 3 || Math.abs(ny - _lbDrag.ty) > 3) _lbDrag.moved = true;
    _lbDrag.tx = nx; _lbDrag.ty = ny;
    el.style.transition = 'none';
    _lbApplyTransform(el);
  }};
  el.onpointerup = function(e) {{
    if (!_lbDrag.on) return;
    _lbDrag.on = false;
    _lbApplyTransform(el);
  }};
}}

document.addEventListener('keydown', function(e) {{
  const lb = document.getElementById('lightbox');
  if (!lb.classList.contains('active')) return;
  if (e.key === 'ArrowLeft') lbNav(-1);
  else if (e.key === 'ArrowRight') lbNav(1);
  else if (e.key === 'Escape') lbClose();
}});

// Prevent page scroll while lightbox is open (non-image wheel is handled here)
document.getElementById('lightbox').addEventListener('wheel', function(e) {{
  if (document.getElementById('lightbox').classList.contains('active')) e.preventDefault();
}}, {{passive: false}});

// ── Virtual scroll (card list) ──────────────────────────────────────────
var _vs = {{rowH: 320, perRow: 1, start: -1, end: -1, calibrated: false}};
var _vsWrap = null, _vsGrid = null;
var _vsCache = {{}};
var _vsRafPending = false;

// Lazy thumbnail loader: only populate card-thumbs when card enters viewport
var _vsThumbObs = new IntersectionObserver(function(entries) {{
  entries.forEach(function(entry) {{
    if (!entry.isIntersecting || entry.target._vsLoaded) return;
    entry.target._vsLoaded = true;
    _vsThumbObs.unobserve(entry.target);
    var u = entry.target._vsUser;
    var thumbItems = u.filesLoaded ? u.files : (u.preview || u.files || []);
    thumbItems.slice(0, 6).forEach(function(item) {{
      var path = _mpath(u, item.f);
      if (item.t === 'video' && item.ht && _THUMB_BASE) {{
        var img = document.createElement('img');
        img.src = _tpath(u, item.f); img.alt = item.f;
        img.className = 'thumb-img'; entry.target.appendChild(img);
      }} else if (item.t === 'video') {{
        var v = document.createElement('video');
        v.setAttribute('muted', ''); v.setAttribute('playsinline', ''); v.setAttribute('preload', 'metadata');
        v.src = path; v.className = 'thumb-video'; entry.target.appendChild(v);
      }}else {{
        var img = document.createElement('img');
        img.src = path; img.alt = item.f;
        img.className = 'thumb-img'; entry.target.appendChild(img);
      }}
    }});
  }});
}}, {{rootMargin: '400px'}});

function _vsInit() {{
  var host = document.getElementById('vs-host');
  _vsWrap = document.createElement('div');
  _vsWrap.style.cssText = 'position:relative;width:100%';
  _vsGrid = document.createElement('div');
  _vsGrid.className = 'cards-grid';
  _vsGrid.style.cssText = 'position:absolute;left:0;right:0';
  _vsWrap.appendChild(_vsGrid);
  host.appendChild(_vsWrap);
  window.addEventListener('scroll', _vsOnScroll, {{passive:true}});
  window.addEventListener('resize', _vsOnResize, {{passive:true}});
  // Defer to after browser layout so offsetWidth is correct
  requestAnimationFrame(_vsRefresh);
}}

function _vsOnScroll() {{
  if (_vsRafPending) return;
  _vsRafPending = true;
  requestAnimationFrame(function() {{ _vsRafPending = false; _vsUpdate(); _mgScroll(); }});
}}

function _vsOnResize() {{
  _vs.calibrated = false;
  _mgResize();
  requestAnimationFrame(_vsRefresh);
}}

function _vsRefresh() {{
  var w = _vsWrap.offsetWidth || window.innerWidth || 900;
  var gap = 16;
  var newPerRow = Math.max(1, Math.floor((w + gap) / (280 + gap)));
  if (newPerRow !== _vs.perRow) {{
    _vsCache = {{}};
    _vs.start = -1; _vs.end = -1;
    _vs.perRow = newPerRow;
  }}
  // Compute rowH from CSS: thumbs aspect-ratio 3:2 + card-info ~64px + gap
  var cardWidth = (w - (newPerRow - 1) * gap) / newPerRow;
  _vs.rowH = Math.ceil(cardWidth * (2 / 3) + 64) + gap;
  _vs.calibrated = false;  // re-calibrate after layout with new width
  _vsWrap.style.height = (Math.ceil(_visibleUsers.length / _vs.perRow) * _vs.rowH) + 'px';
  _vsUpdate();
}}

function _vsUpdate() {{
  if (!_vsWrap || document.getElementById('view-cards').style.display === 'none') return;
  var scrollY = window.scrollY;
  var viewH = window.innerHeight;
  var wrapTop = _vsWrap.getBoundingClientRect().top + scrollY;
  var rel = Math.max(0, scrollY - wrapTop);
  var BUFFER = 4;
  var firstRow = Math.max(0, Math.floor(rel / _vs.rowH) - BUFFER);
  var lastRow = Math.min(
    Math.ceil(_visibleUsers.length / _vs.perRow),
    Math.ceil((rel + viewH) / _vs.rowH) + BUFFER
  );
  var newStart = firstRow * _vs.perRow;
  var newEnd = Math.min(_visibleUsers.length, lastRow * _vs.perRow);
  if (newStart === _vs.start && newEnd === _vs.end) return;

  var prevStart = _vs.start, prevEnd = _vs.end;
  _vs.start = newStart; _vs.end = newEnd;
  _vsGrid.style.top = (firstRow * _vs.rowH) + 'px';

  var isFirst = prevStart < 0;
  var overlap = isFirst ? 0 : Math.max(0, Math.min(prevEnd, newEnd) - Math.max(prevStart, newStart));
  var prevSize = Math.max(1, prevEnd - prevStart);
  if (isFirst || overlap < prevSize * 0.4) {{
    _vsGrid.innerHTML = '';
    for (var i = newStart; i < newEnd; i++) {{
      if (!_vsCache[i]) _vsCache[i] = _vsCard(i);
      _vsGrid.appendChild(_vsCache[i]);
    }}
  }} else {{
    var anchor = _vsGrid.firstChild || null;
    for (var i = Math.min(prevStart, newEnd) - 1; i >= newStart; i--) {{
      if (!_vsCache[i]) _vsCache[i] = _vsCard(i);
      _vsGrid.insertBefore(_vsCache[i], anchor);
      anchor = _vsCache[i];
    }}
    for (var i = Math.max(prevEnd, newStart); i < newEnd; i++) {{
      if (!_vsCache[i]) _vsCache[i] = _vsCard(i);
      _vsGrid.appendChild(_vsCache[i]);
    }}
    for (var i = prevStart; i < Math.min(newStart, prevEnd); i++) {{
      if (_vsCache[i] && _vsCache[i].parentNode) _vsGrid.removeChild(_vsCache[i]);
    }}
    for (var i = Math.max(newEnd, prevStart); i < prevEnd; i++) {{
      if (_vsCache[i] && _vsCache[i].parentNode) _vsGrid.removeChild(_vsCache[i]);
    }}
  }}

  // Calibrate actual row height once; only update wrap height (no re-render)
  if (!_vs.calibrated && _vsGrid.children.length > 0) {{
    var h = _vsGrid.children[0].getBoundingClientRect().height;
    if (h > 10) {{
      _vs.calibrated = true;
      _vs.rowH = Math.ceil(h) + 16;
      _vsWrap.style.height = (Math.ceil(_visibleUsers.length / _vs.perRow) * _vs.rowH) + 'px';
      // No re-render: currently visible cards are already correct in DOM
    }}
  }}
}}

function _vsCard(idx) {{
  var u = _visibleUsers[idx];
  var card = document.createElement('div');
  card.className = 'card' + (_userSelMode && _userSelSet.has(u.uid) ? ' card-selected' : '');
  card.setAttribute('role', 'button');
  card.setAttribute('tabindex', '0');
  var chk = document.createElement('span');
  chk.className = 'card-sel-check';
  if (_userSelSet.has(u.uid)) chk.textContent = '✓';
  card.appendChild(chk);
  card.onclick = (function(i, us, c, ck) {{
    return function() {{
      if (_userSelMode) {{
        if (_userSelSet.has(us.uid)) {{
          _userSelSet.delete(us.uid);
          c.classList.remove('card-selected');
          ck.textContent = '';
        }} else {{
          _userSelSet.add(us.uid);
          c.classList.add('card-selected');
          ck.textContent = '✓';
        }}
        _updateUserSelBar();
      }} else {{
        showUser(i);
      }}
    }};
  }})(idx, u, card, chk);
  card.onkeydown = (function(i) {{ return function(e) {{ if (e.key==='Enter'||e.key===' ') showUser(i); }}; }})(idx);

  var thumbs = document.createElement('div');
  thumbs.className = 'card-thumbs';
  thumbs._vsUser = u;
  if (!thumbs._vsLoaded) _vsThumbObs.observe(thumbs);

  var infoText = document.createElement('div');
  infoText.className = 'card-info-text';
  infoText.innerHTML = '<span class="card-name">' + _hesc(u.display) + '</span>'
    + (u.screen ? '<span class="card-handle">@' + _hesc(u.screen) + '</span>' : '');
  var badge = document.createElement('span');
  badge.className = 'card-count';
  badge.textContent = _countFiles(u) + ' \u5f20';
  var info = document.createElement('div');
  info.className = 'card-info';
  info.appendChild(infoText); info.appendChild(badge);

  card.appendChild(thumbs); card.appendChild(info);
  card.oncontextmenu = (function(u) {{
    return function(e) {{
      _showCtxMenu(e, [{{label:'删除此用户（含全部媒体）', danger:true, action:function(){{_deleteUser(u);}}}}]);
    }};
  }})(u);
  return card;
}}

function _hesc(s) {{
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}}

function onSearch(q) {{
  _visibleUsers = _buildVisibleUsers(q.trim());
  _vsCache = {{}};
  _vs.start = -1; _vs.end = -1;
  _vsRefresh();
  document.getElementById('topbar-meta').textContent =
    _visibleUsers.length + ' 位用户 · ' +
    _visibleUsers.reduce(function(s,u){{return s+_countFiles(u);}},0) + ' 张媒体';
}}

function setFilter(f) {{
  _mediaFilter = f;
  document.querySelectorAll('.ft').forEach(function(b) {{ b.classList.toggle('active', b.dataset.f === f); }});
  _renderDetailGrid();
}}

/* ─── Media grid virtual scroll ─── */
var _mgVS = {{ items: [], cols: 1, rowH: 0, rows: 0, start: -1, end: -1, cache: new Map() }};

function _mgMeasure(grid) {{
  var W = grid.clientWidth || grid.offsetWidth;
  var gap = 3, minW = 200;
  var cols = Math.max(1, Math.floor((W + gap) / (minW + gap)));
  var itemW = (W - gap * (cols - 1)) / cols;
  _mgVS.cols = cols;
  _mgVS.rowH = itemW + gap;
  _mgVS.rows = Math.ceil(_mgVS.items.length / cols);
}}

function _mgCreateItem(u, item, globalIdx) {{
  var div = document.createElement('div');
  div.className = 'media-item' + (_selMode && _selSet.has(item.f) ? ' sel-active' : '');
  var path = _mpath(u, item.f);
  if (item.t === 'video' && item.ht && _THUMB_BASE) {{
    var img = document.createElement('img');
    img.src = _tpath(u, item.f); img.alt = item.f; img.loading = 'lazy';
    div.appendChild(img);
    var ov = document.createElement('div'); ov.className = 'play-ov'; div.appendChild(ov);
  }} else if (item.t === 'video') {{
    var v = document.createElement('video');
    v.setAttribute('muted', ''); v.setAttribute('playsinline', ''); v.setAttribute('preload', 'none');
    v.src = path;
    div.appendChild(v);
    var ov2 = document.createElement('div'); ov2.className = 'play-ov'; div.appendChild(ov2);
  }} else {{
    var img2 = document.createElement('img');
    img2.src = path; img2.alt = item.f; img2.loading = 'lazy';
    div.appendChild(img2);
  }}
  if (item.ts) {{
    var dateEl = document.createElement('span');
    dateEl.className = 'media-item-date';
    dateEl.textContent = _fmtDate(item.ts);
    div.appendChild(dateEl);
  }}
  var chk = document.createElement('span');
  chk.className = 'sel-check';
  if (_selSet.has(item.f)) chk.textContent = '✓';
  div.appendChild(chk);
  div.onclick = (function(it, idx, d, ck) {{
    return function() {{
      if (_selMode) {{
        if (_selSet.has(it.f)) {{ _selSet.delete(it.f); d.classList.remove('sel-active'); ck.textContent = ''; }}
        else {{ _selSet.add(it.f); d.classList.add('sel-active'); ck.textContent = '✓'; }}
        _updateSelBar();
      }} else {{
        lbOpen(idx);
      }}
    }};
  }})(item, globalIdx, div, chk);
  div.oncontextmenu = (function(it) {{
    return function(e) {{
      _showCtxMenu(e, [{{label:'删除此媒体', danger:true, action:function(){{_deleteMedia(currentUser, it);}}}}]);
    }};
  }})(item);
  return div;
}}

function _mgApplyRange(newStart, newEnd) {{
  var mg = _mgVS;
  var grid = document.getElementById('media-grid');
  var u = currentUser;
  if (!u || !grid) return;
  var firstIdx = newStart * mg.cols;
  var lastIdx = Math.min(mg.items.length - 1, (newEnd + 1) * mg.cols - 1);
  var prevFirst = mg.start < 0 ? firstIdx : mg.start * mg.cols;
  var prevLast = mg.end < 0 ? -1 : Math.min(mg.items.length - 1, (mg.end + 1) * mg.cols - 1);
  // Remove top items scrolled out
  for (var ri = prevFirst; ri < firstIdx; ri++) {{
    var el = mg.cache.get(ri);
    if (el && el.parentNode) el.parentNode.removeChild(el);
    mg.cache.delete(ri);
  }}
  // Remove bottom items scrolled out
  for (var ri2 = lastIdx + 1; ri2 <= prevLast; ri2++) {{
    var el2 = mg.cache.get(ri2);
    if (el2 && el2.parentNode) el2.parentNode.removeChild(el2);
    mg.cache.delete(ri2);
  }}
  // Prepend new top items
  if (mg.start >= 0 && firstIdx < prevFirst) {{
    var refNode = grid.firstChild;
    for (var ni = firstIdx; ni < prevFirst && ni <= lastIdx; ni++) {{
      if (!mg.cache.has(ni)) {{
        var nd = _mgCreateItem(u, mg.items[ni], ni);
        mg.cache.set(ni, nd);
        grid.insertBefore(nd, refNode);
      }}
    }}
  }}
  // Append new bottom items (also handles initial full render when prevLast=-1)
  var appendStart = Math.max(firstIdx, prevLast + 1);
  for (var ai = appendStart; ai <= lastIdx; ai++) {{
    if (!mg.cache.has(ai)) {{
      var nd2 = _mgCreateItem(u, mg.items[ai], ai);
      mg.cache.set(ai, nd2);
      grid.appendChild(nd2);
    }}
  }}
  grid.style.paddingTop = (newStart * mg.rowH) + 'px';
  var botRows = Math.max(0, mg.rows - newEnd - 1);
  grid.style.paddingBottom = (botRows * mg.rowH) + 'px';
  mg.start = newStart;
  mg.end = newEnd;
}}

function _mgScroll() {{
  if (document.getElementById('view-detail').style.display === 'none') return;
  var mg = _mgVS;
  if (mg.rowH === 0 || mg.cols === 0 || mg.rows === 0) return;
  var grid = document.getElementById('media-grid');
  if (!grid) return;
  var scrollY = window.scrollY;
  var viewH = window.innerHeight;
  var gridTop = grid.getBoundingClientRect().top + scrollY;
  var relScroll = Math.max(0, scrollY - gridTop);
  var BUFFER = 3;
  var newStart = Math.max(0, Math.floor(relScroll / mg.rowH) - BUFFER);
  var newEnd = Math.min(mg.rows - 1, Math.ceil((relScroll + viewH) / mg.rowH) + BUFFER);
  if (newStart === mg.start && newEnd === mg.end) return;
  _mgApplyRange(newStart, newEnd);
}}

function _mgInit(files) {{
  _mgVS.items = files;
  _mgVS.start = -1;
  _mgVS.end = -1;
  _mgVS.cache = new Map();
  _mgVS.rowH = 0;
  var grid = document.getElementById('media-grid');
  if (!grid) return;
  grid.style.paddingTop = '';
  grid.style.paddingBottom = '';
  grid.innerHTML = '';
  grid.classList.toggle('sel-mode', _selMode);
  if (files.length === 0) {{ _mgVS.rows = 0; _mgVS.cols = 1; return; }}
  _mgMeasure(grid);
  _mgScroll();
}}

function _mgResize() {{
  if (!currentUser || document.getElementById('view-detail').style.display === 'none') return;
  var grid = document.getElementById('media-grid');
  if (!grid || _mgVS.rowH === 0) return;
  var oldCols = _mgVS.cols;
  _mgMeasure(grid);
  if (_mgVS.cols !== oldCols) {{
    // Column count changed — full reset
    _mgVS.cache = new Map();
    _mgVS.start = -1; _mgVS.end = -1;
    grid.style.paddingTop = '';
    grid.style.paddingBottom = '';
    grid.innerHTML = '';
    _mgScroll();
  }}
}}

function _renderDetailGrid() {{
  var u = currentUser;
  if (!u) return;
  var files = _applySortFilter(u.files);
  lbFiles = files;
  _mgInit(files);
  var suffix = _mediaFilter !== 'all' ? '（已筛选）' : '';
  document.getElementById('topbar-meta').textContent = files.length + ' 张媒体' + suffix;
}}

document.addEventListener('DOMContentLoaded', function() {{
  function _init() {{
    _visibleUsers = _buildVisibleUsers('');
    _vsInit();
    // Hide "最近" sort button if no user has latest data
    if (!USERS.some(function(u) {{ return u.latest; }})) {{
      var btn = document.getElementById('ust-recent');
      if (btn) btn.style.display = 'none';
    }}
    document.getElementById('ust-wrap').style.display = 'flex';
    var hash = location.hash;
    var uid = hash.startsWith('#user-') ? decodeURIComponent(hash.slice(6)) : '';
    if (uid) {{
      var idx = _visibleUsers.findIndex(function(u) {{ return u.uid === uid; }});
      if (idx >= 0) {{
        history.replaceState({{view:'user',uid:uid}}, '', location.pathname + location.search + hash);
        showUser(idx, true);
        return;
      }}
    }}
    history.replaceState({{view:'cards'}}, '', location.pathname + location.search);
  }}
  if (_API_MODE) {{
    _showPageLoading('正在加载用户列表…');
    fetch('/api/users')
      .then(function(r) {{ return r.json(); }})
      .then(function(data) {{ USERS = data; _init(); _hidePageLoading(); }})
      .catch(function() {{
        _hidePageLoading();
        document.getElementById('vs-host').innerHTML =
          '<div style="padding:40px;text-align:center;color:#f4212e;font-size:15px">加载用户列表失败，请刷新页面</div>';
      }});
  }} else {{
    _init();
    _hidePageLoading();
  }}
}});

window.addEventListener('popstate', function(e) {{
  var state = e.state || {{view:'cards'}};
  if (state.view === 'user') {{
    _visibleUsers = _buildVisibleUsers('');
    var idx = _visibleUsers.findIndex(function(u) {{ return u.uid === state.uid; }});
    if (idx >= 0) showUser(idx, true); else showCards(true);
  }} else {{
    showCards(true);
  }}
}});
</script>
</body>
</html>"""
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
