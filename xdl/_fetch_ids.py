"""One-shot script to extract current GraphQL query IDs from X's JS bundle."""
import asyncio
import re
import httpx

TARGETS = ["UserByScreenName", "UserTweets", "Likes", "Viewer", "TweetDetail"]

async def fetch_ids(proxy: str | None = None) -> dict:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with httpx.AsyncClient(
        headers=headers, follow_redirects=True, timeout=30, proxy=proxy
    ) as client:
        print("Fetching x.com home page...")
        resp = await client.get("https://x.com/")
        print(f"  Status: {resp.status_code}")

        # Find JS bundle URLs (abs.twimg.com/responsive-web/client-web/*.js)
        js_urls: list[str] = re.findall(
            r'https://abs\.twimg\.com/responsive-web/client-web/[^"\']+\.js',
            resp.text,
        )
        # Deduplicate preserving order
        seen: set[str] = set()
        js_urls = [u for u in js_urls if not (u in seen or seen.add(u))]  # type: ignore[func-returns-value]
        print(f"  Found {len(js_urls)} JS bundles")

        found: dict[str, str] = {}
        for js_url in js_urls:
            short = js_url.split("/")[-1]
            print(f"  Scanning {short} …", end=" ", flush=True)
            try:
                r = await client.get(js_url, timeout=20)
                if r.status_code != 200:
                    print(f"skip ({r.status_code})")
                    continue
                text = r.text
                hits = 0
                for target in TARGETS:
                    if target in text and target not in found:
                        # Pattern used in X's minified JS:
                        # queryId:"<ID>",operationName:"<Name>"
                        m = re.search(
                            r'queryId:"([^"]+)",operationName:"' + re.escape(target) + '"',
                            text,
                        )
                        if m:
                            found[target] = m.group(1)
                            hits += 1
                print(f"found {hits}" if hits else "nothing")
            except Exception as exc:
                print(f"error: {exc}")

            if len(found) >= len(TARGETS):
                break

        return found


if __name__ == "__main__":
    from xdl.config import load_config
    cfg = load_config()
    proxy = cfg.get("proxy") or None
    print(f"Using proxy: {proxy or '(none)'}\n")
    ids = asyncio.run(fetch_ids(proxy))
    print()
    if ids:
        print("=== Found Query IDs ===")
        for name, qid in ids.items():
            print(f"  {name}: {qid}")
        print()
        print("Run this command to update your config:")
        parts = " ".join(f'--query-id "{k}={v}"' for k, v in ids.items())
        print(f"  xdl config {parts}")
    else:
        print("No query IDs found. X may have changed their JS bundle structure.")
        print("Try getting the IDs manually from browser DevTools → Network.")
