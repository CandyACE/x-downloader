"""Configuration management for X Downloader.

Priority (highest → lowest):
  1. Environment variables (X_AUTH_TOKEN, X_CT0, …)
  2. .env file in the current working directory
  3. ~/.x-downloader/config.json
  4. Built-in defaults
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

CONFIG_PATH = Path.home() / ".x-downloader" / "config.json"

# X Web App bearer token (public value embedded in Twitter's JS bundle)
DEFAULT_BEARER = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I7sAHQdkLCHW3Art"
    "Zw0jjdkWXlFsLXONniP0vsSKVjWp2XEIznNIiHC43bUvEc9Mjw%3DlLXX8VWZQ"
    "0iFwjTDKgMEDIPHEEkAA"
)

# GraphQL query IDs used by the X web client (may change with X updates)
DEFAULT_QUERY_IDS: dict[str, str] = {
    "UserByScreenName": "NimuplG1OB7Fb2btCLdBOw",
    "UserTweets": "V7H0Du3tOkHMEd0YEFTunA",
    "UserMedia": "Uqb0z_IFBrxmPUhQ7pz6GQ",
    "Likes": "kgZtsNAE1IVnW9fDROGm-A",
    "Viewer": "_8ClT24oZ8tpylf_OSuNdg",
    "TweetDetail": "VWFGPVAGkZMGRKGe3GFFnA",
}

DEFAULT_CONFIG: dict = {
    "auth_token": "",
    "ct0": "",
    "bearer_token": DEFAULT_BEARER,
    "output_dir": "./downloads",
    "concurrency": 5,
    "proxy": "",           # e.g. "http://127.0.0.1:7890" or "socks5://127.0.0.1:1080"
    "query_ids": DEFAULT_QUERY_IDS,
    "storage_mode": "folder",  # "folder" | "sqlite"
    "db_path": "",             # path to .db file; empty = output_dir/x-gallery.db
    "scan_delay": 1.0,         # seconds to wait between API pages (anti-rate-limit)
}


def load_config() -> dict:
    # 1. Load .env from current working directory (does not override real env vars)
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)

    # 2. Load from JSON config file
    cfg = DEFAULT_CONFIG.copy()
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        cfg.update(saved)
        cfg["query_ids"] = {**DEFAULT_QUERY_IDS, **saved.get("query_ids", {})}

    # 3. Environment variables override everything
    _env_overrides = {
        "auth_token": os.getenv("X_AUTH_TOKEN"),
        "ct0": os.getenv("X_CT0"),
        "bearer_token": os.getenv("X_BEARER_TOKEN"),
        "output_dir": os.getenv("X_OUTPUT_DIR"),
        "concurrency": os.getenv("X_CONCURRENCY"),
        "proxy": os.getenv("X_PROXY"),
    }
    for key, value in _env_overrides.items():
        if value is not None:
            cfg[key] = int(value) if key == "concurrency" else value

    return cfg


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def get_config_path() -> Path:
    return CONFIG_PATH
