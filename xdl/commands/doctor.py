"""'doctor' command — diagnose credentials and API connectivity."""
from __future__ import annotations

import asyncio
import json

import click
import httpx
from rich.table import Table

from .._helpers import console
from ..auth import build_headers
from ..config import get_config_path, load_config


@click.command("doctor")
def cmd_doctor() -> None:
    """Diagnose credentials and API connectivity."""
    asyncio.run(_run_doctor())


async def _run_doctor() -> None:
    """Diagnose configuration and API connectivity."""
    cfg = load_config()
    t = Table(title="X Downloader — Diagnostics", show_header=False, padding=(0, 2))

    def _mask(val: str, show: int = 6) -> str:
        if not val:
            return "[red]NOT SET[/red]"
        return f"[green]{val[:show]}…[/green] ({len(val)} chars)"

    t.add_row("auth_token", _mask(cfg.get("auth_token", "")))
    t.add_row("ct0", _mask(cfg.get("ct0", ""), 8))
    t.add_row("bearer_token", _mask(cfg.get("bearer_token", ""), 20))
    t.add_row("output_dir", cfg.get("output_dir", ""))
    t.add_row("proxy", cfg.get("proxy", "") or "[dim]none[/dim]")
    t.add_row("config file", str(get_config_path()))
    console.print(t)

    if not cfg.get("auth_token") or not cfg.get("ct0"):
        console.print(
            "\n[red]✗ Credentials not configured.[/red]\n"
            "Run: [bold]xdl config --auth-token <token> --ct0 <ct0>[/bold]\n"
            "Or create a [bold].env[/bold] file with X_AUTH_TOKEN and X_CT0."
        )
        return

    headers = build_headers(cfg["auth_token"], cfg["ct0"], cfg["bearer_token"])
    proxy = cfg.get("proxy") or None

    console.print("\n[cyan]Testing API connectivity…[/cyan]")

    qid = cfg["query_ids"]["UserByScreenName"]
    gql_url = f"https://x.com/i/api/graphql/{qid}/UserByScreenName"
    gql_params = {
        "variables": json.dumps({"screen_name": "x", "withSafetyModeUserFields": True}),
        "features": json.dumps({
            "hidden_profile_likes_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "responsive_web_graphql_timeline_navigation_enabled": True,
        }),
        "fieldToggles": json.dumps({"withAuxiliaryUserLabels": False}),
    }

    settings_url = "https://x.com/i/api/1.1/account/settings.json"

    def _status_label(code: int, name: str) -> str:
        if code == 200:
            return f"  [green]✓[/green] {name} → 200 OK"
        if code == 401:
            return (
                f"  [red]✗[/red] {name} → 401 Unauthorized\n"
                "    [yellow]→ auth_token or ct0 is expired. "
                "Re-copy them from x.com browser DevTools.[/yellow]"
            )
        if code == 403:
            return (
                f"  [red]✗[/red] {name} → 403 Forbidden\n"
                "    [yellow]→ Cookie rejected. Ensure you copied from x.com (not twitter.com).[/yellow]"
            )
        return f"  [yellow]?[/yellow] {name} → {code}"

    async def _test_connectivity(client_proxy: str | None, label: str) -> None:
        async with httpx.AsyncClient(
            headers=headers, follow_redirects=True, timeout=15.0, proxy=client_proxy
        ) as client:
            for name, url, params in [
                ("UserByScreenName GraphQL", gql_url, gql_params),
                ("account/settings.json", settings_url, {}),
            ]:
                try:
                    resp = await client.get(url, params=params)
                    console.print(_status_label(resp.status_code, f"{name} [{label}]"))
                    if resp.status_code == 200 and "UserByScreenName" in name:
                        try:
                            result = resp.json()["data"]["user"]["result"]
                            sn = (
                                result.get("core", {}).get("screen_name")
                                or result.get("legacy", {}).get("screen_name")
                            )
                            if sn:
                                console.print(f"    [dim]→ Resolved @{sn} successfully[/dim]")
                        except Exception:
                            pass
                except Exception as exc:
                    console.print(f"  [red]✗[/red] {name} [{label}] → Error: {exc}")

    await _test_connectivity(proxy, "via proxy" if proxy else "direct")
    if proxy:
        console.print("\n[cyan]Re-testing without proxy (direct connection)…[/cyan]")
        await _test_connectivity(None, "direct")

    console.print(
        "\n[dim]Tip: get auth_token & ct0 from browser DevTools → "
        "Application → Cookies → https://x.com[/dim]\n"
        "[dim]Tip: if GraphQL returns 404, run [bold]python _fetch_ids.py[/bold] "
        "to auto-update query IDs[/dim]"
    )
