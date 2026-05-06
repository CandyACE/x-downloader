"""Parse X (Twitter) data archive files.

X archive structure:
  <archive_dir>/
    data/
      like.js          — liked tweets (may be split into like.part0.js, etc.)
      tweets.js        — your own tweets
      ...

like.js format (JavaScript variable assignment, not pure JSON):
  window.YTD.like.part0 = [{"like": {"tweetId": "...", ...}}, ...]
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _strip_js_assignment(content: str) -> str:
    """Strip the JS variable prefix from a YTD archive file and return raw JSON."""
    # e.g. 'window.YTD.like.part0 = [...]'
    return re.sub(r"^window\.\S+\s*=\s*", "", content.strip())


def _load_parts(data_dir: Path, stem: str) -> list:
    """Load all parts of a YTD archive file (stem.js, stem.part0.js, …) as one list."""
    pattern = f"{stem}*.js"
    files = sorted(data_dir.glob(pattern))
    if not files:
        return []
    items: list = []
    for path in files:
        raw = _strip_js_assignment(path.read_text(encoding="utf-8"))
        items.extend(json.loads(raw))
    return items


def parse_like_ids(archive_dir: Path) -> list[str]:
    """
    Return all liked tweet IDs from the X archive, preserving order (newest first).

    *archive_dir* can be the top-level archive folder (containing ``data/``)
    or the ``data/`` folder itself.
    """
    data_dir = archive_dir / "data"
    if not data_dir.exists():
        data_dir = archive_dir  # caller passed data/ directly

    items = _load_parts(data_dir, "like")
    if not items:
        raise FileNotFoundError(
            f"No like*.js files found in {data_dir}.\n"
            "Make sure you're pointing to the extracted X archive folder."
        )

    ids: list[str] = []
    for item in items:
        # Two formats observed in the wild:
        #   {"like": {"tweetId": "123"}}   — older archives
        #   {"tweetId": "123"}             — newer archives
        tid = (
            item.get("like", {}).get("tweetId")
            or item.get("tweetId")
        )
        if tid:
            ids.append(str(tid))
    return ids
