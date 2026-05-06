"""X (Twitter) internal GraphQL API client."""
from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, AsyncIterator

if TYPE_CHECKING:
    from collections.abc import Callable

import httpx
from rich.console import Console

console = Console()

# GraphQL feature flags required by X's timeline endpoints
_TWEET_FEATURES = {
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "rweb_video_timestamps_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

_USER_FEATURES = {
    "hidden_profile_likes_enabled": True,
    "hidden_profile_subscriptions_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "verified_phone_label_enabled": False,
    "subscriptions_verification_info_is_identity_verified_enabled": True,
    "subscriptions_verification_info_verified_since_enabled": True,
    "highlights_tweets_tab_ui_enabled": True,
    "responsive_web_twitter_article_notes_tab_enabled": True,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "responsive_web_graphql_timeline_navigation_enabled": True,
}

_USER_MEDIA_FEATURES = {
    "rweb_video_screen_enabled": False,
    "rweb_cashtags_enabled": True,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "responsive_web_profile_redirect_enabled": False,
    "rweb_tipjar_consumption_enabled": False,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": False,
    "responsive_web_jetfuel_frame": True,
    "responsive_web_grok_share_attachment_enabled": True,
    "responsive_web_grok_annotations_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "content_disclosure_indicator_enabled": True,
    "content_disclosure_ai_generated_indicator_enabled": True,
    "responsive_web_grok_show_grok_translated_post": True,
    "responsive_web_grok_analysis_button_from_backend": True,
    "post_ctas_fetch_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": False,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_grok_imagine_annotation_enabled": True,
    "responsive_web_grok_community_note_auto_translation_is_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}

_BASE = "https://x.com"


class XClient:
    """Async client for X internal GraphQL API using cookie authentication."""

    def __init__(
        self,
        headers: dict[str, str],
        query_ids: dict[str, str],
        proxy: str | None = None,
    ) -> None:
        self._headers = headers
        self._query_ids = query_ids
        self._proxy = proxy or None
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "XClient":
        self._http = httpx.AsyncClient(
            headers=self._headers,
            http2=True,
            follow_redirects=True,
            timeout=30.0,
            proxy=self._proxy,
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._http:
            await self._http.aclose()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_user_id(self, screen_name: str) -> tuple[str, str, str]:
        """Return (user_id, canonical_screen_name, full_name) for a given screen name."""
        qid = self._query_ids["UserByScreenName"]
        url = f"{_BASE}/i/api/graphql/{qid}/UserByScreenName"
        variables = {"screen_name": screen_name, "withSafetyModeUserFields": True}
        params = {
            "variables": json.dumps(variables),
            "features": json.dumps(_USER_FEATURES),
            "fieldToggles": json.dumps({"withAuxiliaryUserLabels": False}),
        }
        data = await self._get(url, params)
        user_node = data.get("data", {}).get("user")
        if not user_node:
            raise RuntimeError(
                f"User @{screen_name} not found (account may not exist, "
                "be suspended, or be set to private)."
            )
        result = user_node["result"]
        user_id: str = result["rest_id"]
        # X moved screen_name from legacy to core in newer API responses
        canonical: str = (
            result.get("core", {}).get("screen_name")
            or result.get("legacy", {}).get("screen_name")
            or screen_name
        )
        full_name: str = (
            result.get("core", {}).get("name")
            or result.get("legacy", {}).get("name")
            or canonical
        )
        return user_id, canonical, full_name

    async def get_me(self) -> tuple[str, str, str]:
        """Return (user_id, screen_name) of the authenticated user via GraphQL Viewer query."""
        qid = self._query_ids.get("Viewer", "_8ClT24oZ8tpylf_OSuNdg")
        url = f"{_BASE}/i/api/graphql/{qid}/Viewer"
        params = {
            "variables": "{}",
            "features": json.dumps(_USER_FEATURES),
        }
        data = await self._get(url, params)
        result = (
            data.get("data", {})
            .get("viewer", {})
            .get("user_results", {})
            .get("result", {})
        )
        if not result:
            raise RuntimeError(
                "Could not determine your account — Viewer query returned empty data.\n"
                "Check that auth_token and ct0 are correct and not expired.\n"
                "Use 'xdl likes --me YOUR_USERNAME' to bypass this check."
            )
        user_id: str = result["rest_id"]
        screen_name: str = (
            result.get("core", {}).get("screen_name")
            or result.get("legacy", {}).get("screen_name")
            or ""
        )
        if not screen_name:
            raise RuntimeError(
                "Viewer query succeeded but screen_name not found in response.\n"
                "Use 'xdl likes --me YOUR_USERNAME' to bypass this check."
            )
        full_name: str = (
            result.get("core", {}).get("name")
            or result.get("legacy", {}).get("name")
            or screen_name
        )
        return user_id, screen_name, full_name

    async def iter_user_tweets(
        self,
        user_id: str,
        batch: int = 20,
        start_cursor: str | None = None,
        on_cursor: "Callable[[str], None] | None" = None,
        page_delay: float = 1.0,
        verbose: bool = False,
    ) -> AsyncIterator[dict]:
        """Yield raw tweet result dicts from a user's timeline."""
        qid = self._query_ids["UserTweets"]
        url = f"{_BASE}/i/api/graphql/{qid}/UserTweets"
        base_vars: dict = {
            "userId": user_id,
            "count": batch,
            "includePromotedContent": False,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
            "withV2Timeline": True,
        }
        async for entry in self._iter_timeline(url, base_vars, start_cursor, on_cursor, page_delay, verbose):
            yield entry

    async def iter_user_media(
        self,
        user_id: str,
        batch: int = 20,
        start_cursor: str | None = None,
        on_cursor: "Callable[[str], None] | None" = None,
        page_delay: float = 1.0,
        verbose: bool = False,
    ) -> AsyncIterator[dict]:
        """Yield raw tweet result dicts from a user's Media tab (only media-containing tweets)."""
        qid = self._query_ids.get("UserMedia", "Uqb0z_IFBrxmPUhQ7pz6GQ")
        url = f"{_BASE}/i/api/graphql/{qid}/UserMedia"
        base_vars: dict = {
            "userId": user_id,
            "count": batch,
            "includePromotedContent": False,
            "withClientEventToken": False,
            "withBirdwatchNotes": False,
            "withVoice": True,
            "withV2Timeline": True,
        }
        async for entry in self._iter_timeline(url, base_vars, start_cursor, on_cursor, page_delay, verbose, features=_USER_MEDIA_FEATURES):
            yield entry

    async def iter_likes(
        self,
        user_id: str,
        batch: int = 20,
        start_cursor: str | None = None,
        on_cursor: "Callable[[str], None] | None" = None,
        page_delay: float = 1.0,
        verbose: bool = False,
    ) -> AsyncIterator[dict]:
        """Yield raw tweet result dicts from a user's likes timeline."""
        qid = self._query_ids["Likes"]
        url = f"{_BASE}/i/api/graphql/{qid}/Likes"
        base_vars: dict = {
            "userId": user_id,
            "count": batch,
            "includePromotedContent": False,
            "withClientEventToken": False,
            "withBirdwatchNotes": False,
            "withVoice": True,
            "withV2Timeline": True,
        }
        async for entry in self._iter_timeline(url, base_vars, start_cursor, on_cursor, page_delay, verbose):
            yield entry

    async def _iter_timeline(
        self,
        url: str,
        base_vars: dict,
        start_cursor: str | None,
        on_cursor: "Callable[[str], None] | None",
        page_delay: float,
        verbose: bool,
        features: dict | None = None,
    ) -> AsyncIterator[dict]:
        """Shared pagination loop for any timeline-style GraphQL endpoint."""
        cursor: str | None = start_cursor
        page = 0
        consecutive_empty = 0

        while True:
            page += 1
            variables = {**base_vars}
            if cursor:
                variables["cursor"] = cursor

            params = {
                "variables": json.dumps(variables),
                "features": json.dumps(features if features is not None else _TWEET_FEATURES),
            }
            if verbose:
                console.print(
                    f"[dim]→ Fetching page {page}"
                    + (f" (cursor …{cursor[-12:]})" if cursor else "")
                    + "[/dim]"
                )
            try:
                data = await self._get(url, params)
            except httpx.HTTPStatusError as exc:
                console.print(
                    f"[yellow]⚠ API returned {exc.response.status_code} after all retries. "
                    "Stopping scan — progress has been saved, re-run to resume.[/yellow]"
                )
                break

            # Detect API-level errors (HTTP 200 but JSON contains errors array)
            if "errors" in data and data.get("errors"):
                for err in data["errors"]:
                    msg = err.get("message", str(err))
                    console.print(f"[red]⚠ API error: {msg}[/red]")
                if verbose:
                    console.print(f"[dim]Raw response: {json.dumps(data)[:2000]}[/dim]")
                break

            if verbose and "data" not in data:
                console.print(f"[yellow]⚠ Unexpected response shape (no 'data' key).[/yellow]")
                console.print(f"[dim]Raw response: {json.dumps(data)[:2000]}[/dim]")

            entries, next_cursor = _parse_timeline(data, ("data", "user", "result"))
            if verbose:
                console.print(
                    f"[dim]  ← Page {page}: {len(entries)} entries, "
                    f"next_cursor={'yes' if next_cursor else 'none'}[/dim]"
                )
                if not entries:
                    _u = data.get("data", {}).get("user", {}).get("result", {})
                    _tl = (_u.get("timeline_v2", _u.get("timeline", {}))
                           .get("timeline", {}).get("instructions", []))
                    for _ins in _tl[:4]:
                        _itype = _ins.get("type")
                        console.print(f"[dim]  instr type: {_itype}[/dim]")
                        _empty: dict = {}
                        for _e in _ins.get("entries", [])[:8]:
                            console.print(
                                f"[dim]    entryId={_e.get('entryId')!r} "
                                f"entryType={_e.get('content', _empty).get('entryType')!r}[/dim]"
                            )
                        if _itype == "TimelineAddToModule":
                            _mit = _ins.get("moduleItems", _ins.get("entries", []))
                            console.print(f"[dim]    moduleItems count: {len(_mit)}, keys: {list(_mit[0].keys()) if _mit else '[]'}[/dim]")

            for entry in entries:
                yield entry

            if entries:
                consecutive_empty = 0
            else:
                consecutive_empty += 1

            if next_cursor and on_cursor:
                on_cursor(next_cursor)

            if not next_cursor:
                break
            if next_cursor == cursor and not entries:
                console.print("[dim]  End of timeline (cursor not advancing).[/dim]")
                break
            if consecutive_empty >= 3:
                console.print("[dim]  End of timeline (3 consecutive empty pages).[/dim]")
                break
            cursor = next_cursor
            if page_delay > 0:
                await asyncio.sleep(page_delay)

    async def fetch_tweet(self, tweet_id: str) -> dict | None:
        """
        Fetch a single tweet by ID via the TweetDetail endpoint.

        Returns the raw tweet result dict (same format as timeline entries),
        or ``None`` if the tweet is deleted, private, or the query fails.
        """
        qid = self._query_ids.get("TweetDetail", "VWFGPVAGkZMGRKGe3GFFnA")
        url = f"{_BASE}/i/api/graphql/{qid}/TweetDetail"
        variables: dict = {
            "focalTweetId": tweet_id,
            "referrer": "profile",
            "count": 20,
            "includePromotedContent": False,
            "withCommunity": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withBirdwatchNotes": False,
            "withVoice": True,
        }
        params = {
            "variables": json.dumps(variables),
            "features": json.dumps(_TWEET_FEATURES),
            "fieldToggles": json.dumps({"withArticleRichContentState": True}),
        }
        try:
            data = await self._get(url, params)
        except RuntimeError:
            raise  # re-raise auth errors
        except Exception:
            return None

        # TweetDetail may return either _v2 or non-v2 key depending on API version
        conversation = data.get("data", {})
        thread_data = (
            conversation.get("threaded_conversation_with_injections_v2")
            or conversation.get("threaded_conversation_with_injections")
            or {}
        )
        instructions = thread_data.get("instructions", [])
        target_entry = f"tweet-{tweet_id}"
        for instruction in instructions:
            if instruction.get("type") != "TimelineAddEntries":
                continue
            for entry in instruction.get("entries", []):
                if entry.get("entryId") != target_entry:
                    continue
                result = (
                    entry.get("content", {})
                    .get("itemContent", {})
                    .get("tweet_results", {})
                    .get("result")
                )
                return result
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _get(
        self, url: str, params: dict, *, retries: int = 8
    ) -> dict:
        assert self._http is not None, "Client not started – use async with"
        for attempt in range(retries):
            try:
                response = await self._http.get(url, params=params)

                if response.status_code == 429:
                    wait = 60 * (attempt + 1)
                    console.print(
                        f"[yellow]Rate limited (429). Waiting {wait}s…[/yellow]"
                    )
                    await asyncio.sleep(wait)
                    continue

                if response.status_code in (500, 502, 503, 504):
                    wait = 30 * (attempt + 1)
                    console.print(
                        f"[yellow]Server error ({response.status_code}). "
                        f"Waiting {wait}s… (attempt {attempt + 1}/{retries})[/yellow]"
                    )
                    await asyncio.sleep(wait)
                    continue

                if response.status_code == 401:
                    body = {}
                    try:
                        body = response.json()
                    except Exception:
                        pass
                    code = (body.get("errors") or [{}])[0].get("code", 0)
                    if code == 32:
                        raise RuntimeError(
                            "Authentication failed (code 32).\n"
                            "Your auth_token or ct0 cookie has likely expired.\n"
                            "→ Open x.com → F12 → Application → Cookies → x.com\n"
                            "→ Copy fresh auth_token and ct0 values\n"
                            "→ Run: xdl config --auth-token NEW --ct0 NEW\n"
                            "  (or update X_AUTH_TOKEN and X_CT0 in your .env file)\n"
                            "→ Run: xdl doctor   to verify connectivity"
                        )
                    response.raise_for_status()

                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as exc:
                console.print(f"[red]HTTP {exc.response.status_code}: {url}[/red]")
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(10 * (attempt + 1))

            except (httpx.RequestError, RuntimeError):
                raise

        return {}


# ------------------------------------------------------------------
# Timeline parsing helpers
# ------------------------------------------------------------------

def _parse_timeline(
    data: dict, path: tuple[str, ...]
) -> tuple[list[dict], str | None]:
    """
    Navigate to the timeline instructions inside *data* via *path* and
    return (tweet_result_list, next_cursor).
    """
    node = data
    for key in path:
        node = node.get(key, {})

    # UserTweets uses timeline_v2; Likes uses timeline (no _v2)
    instructions: list[dict] = (
        node.get("timeline_v2", node.get("timeline", {}))
        .get("timeline", {})
        .get("instructions", [])
    )

    tweets: list[dict] = []
    cursor: str | None = None

    for instruction in instructions:
        itype = instruction.get("type")
        if itype == "TimelineAddEntries":
            for entry in instruction.get("entries", []):
                entry_id: str = entry.get("entryId", "")
                content: dict = entry.get("content", {})

                if "cursor-bottom" in entry_id:
                    cursor = content.get("value")
                elif content.get("entryType") == "TimelineTimelineItem":
                    result = (
                        content.get("itemContent", {})
                        .get("tweet_results", {})
                        .get("result")
                    )
                    if result:
                        tweets.append(result)
                elif content.get("entryType") == "TimelineTimelineModule":
                    # UserMedia page 1: grid-style module entries; each item
                    # represents one media attachment from the tweet.
                    for module_item in content.get("items", []):
                        result = (
                            module_item.get("item", {})
                            .get("itemContent", {})
                            .get("tweet_results", {})
                            .get("result")
                        )
                        if result:
                            tweets.append(result)

        elif itype == "TimelineAddToModule":
            # UserMedia page 2+: items appended to the existing grid module.
            # Entries are directly in instruction["moduleItems"], each with an
            # "item" key (not wrapped in "content").
            for module_entry in instruction.get("moduleItems", []):
                result = (
                    module_entry.get("item", {})
                    .get("itemContent", {})
                    .get("tweet_results", {})
                    .get("result")
                )
                if result:
                    tweets.append(result)
            # Cursor for TimelineAddToModule may be in a separate
            # TimelineAddEntries instruction on the same page (handled above),
            # or absent if this is the final page.

    return tweets, cursor
