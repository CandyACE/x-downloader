"""Extract media items from X tweet result objects."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass
class MediaItem:
    tweet_id: str
    author_id: str
    author_screen_name: str
    author_full_name: str
    url: str
    filename: str
    media_type: str  # "photo" | "animated_gif"


def _safe_name(name: str) -> str:
    """Strip characters that are invalid in Windows/macOS/Linux folder names."""
    invalid = r'\/:*?"<>|'
    for ch in invalid:
        name = name.replace(ch, "")
    name = " ".join(name.split())  # collapse whitespace
    return name.strip() or "unknown"


def extract_media(tweet_result: dict) -> list[MediaItem]:
    """Return all downloadable media items from a raw tweet result dict."""
    tweet = _normalize(tweet_result)
    if not tweet:
        return []

    legacy: dict = tweet.get("legacy", {})
    tweet_id: str = legacy.get("id_str", "")

    # Author info lives in core.user_results.result
    # X moved screen_name from result.legacy to result.core in newer API
    core = tweet.get("core", {})
    user_result = core.get("user_results", {}).get("result", {})
    user_legacy = user_result.get("legacy", {})
    author_id: str = (
        user_result.get("rest_id")
        or user_legacy.get("id_str")
        or legacy.get("user_id_str", "")
    )
    author_screen: str = (
        user_result.get("core", {}).get("screen_name")
        or user_legacy.get("screen_name")
        or author_id
    )
    author_full: str = _safe_name(
        user_result.get("core", {}).get("name")
        or user_legacy.get("name")
        or author_screen
    )

    media_list: list[dict] = legacy.get("extended_entities", {}).get("media", [])
    items: list[MediaItem] = []

    for idx, media in enumerate(media_list):
        mtype = media.get("type", "")

        if mtype == "photo":
            base_url: str = media.get("media_url_https", "")
            if not base_url:
                continue
            ext = PurePosixPath(base_url).suffix.lstrip(".") or "jpg"
            # ?name=orig fetches the original full-resolution image
            url = f"{base_url}?name=orig"
            items.append(MediaItem(
                tweet_id=tweet_id,
                author_id=author_id,
                author_screen_name=author_screen,
                author_full_name=author_full,
                url=url,
                filename=f"{tweet_id}_{idx:02d}.{ext}",
                media_type="photo",
            ))

        elif mtype == "animated_gif":
            variants: list[dict] = media.get("video_info", {}).get("variants", [])
            mp4_urls = [v["url"] for v in variants if v.get("content_type") == "video/mp4"]
            if not mp4_urls:
                continue
            items.append(MediaItem(
                tweet_id=tweet_id,
                author_id=author_id,
                author_screen_name=author_screen,
                author_full_name=author_full,
                url=mp4_urls[0],
                filename=f"{tweet_id}_{idx:02d}.mp4",
                media_type="animated_gif",
            ))

        elif mtype == "video":
            variants = media.get("video_info", {}).get("variants", [])
            # Pick highest-bitrate MP4
            mp4s = [v for v in variants if v.get("content_type") == "video/mp4"]
            if not mp4s:
                continue
            best = max(mp4s, key=lambda v: v.get("bitrate", 0))
            items.append(MediaItem(
                tweet_id=tweet_id,
                author_id=author_id,
                author_screen_name=author_screen,
                author_full_name=author_full,
                url=best["url"],
                filename=f"{tweet_id}_{idx:02d}.mp4",
                media_type="video",
            ))

    return items


def _normalize(tweet_result: dict) -> dict | None:
    """Unwrap TweetWithVisibilityResults and similar wrappers."""
    typename = tweet_result.get("__typename", "")
    if typename == "TweetWithVisibilityResults":
        return tweet_result.get("tweet", {})
    if typename in ("Tweet", "") :
        return tweet_result
    return None
