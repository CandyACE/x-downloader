# xdl — X (Twitter) Media Downloader

> **The English README has moved to [README.md](README.md).**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[中文](README.zh-CN.md) | [English](README.md)


---

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Authentication](#authentication)
- [Configuration](#configuration)
- [Usage](#usage)
- [Storage Modes](#storage-modes)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Proxy Support](#proxy-support)
- [Contributing](#contributing)
- [Disclaimer](#disclaimer)
- [License](#license)

---

## Features

| Feature | Description |
|---------|-------------|
| 🖼️ **User Media** | Download all images, GIFs, and videos from any user's tweets; `--media-only` queries the Media tab directly |
| ❤️ **Liked Tweets** | Download media from your liked tweets, organized by original author |
| 🐦 **Single Tweet** | Download media from a single tweet by ID or URL |
| 🔍 **Type Filter** | `--image-only` / `--video-only` to download only images (incl. GIFs) or videos |
| 📦 **Two Storage Modes** | `folder` (directory tree) or `sqlite` (single `.db` file) |
| 🌐 **Built-in Gallery** | `xdl serve` starts a local HTTP server to visually browse downloaded media |
| 🔄 **Incremental & Resume** | Second run only downloads new content; Ctrl+C resumes from where it left off |
| ⚡ **Concurrent Downloads** | Async multi-threaded, default 5 concurrent connections |
| 📁 **Archive Import** | Bulk import liked media from X data archive (`like.js`) |
| 🎞️ **Video Thumbnails** | Auto-generate MP4 preview images via ffmpeg |

---

## Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/download.html) *(optional, for video thumbnails)*

---

## Installation

```bash
git clone https://github.com/yourusername/x-downloader.git
cd x-downloader

python -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

pip install -e .
```

> **Optional:** Video thumbnails require [ffmpeg](https://ffmpeg.org/download.html) to be installed on your system.  
> SOCKS5 proxy support requires `httpx[socks]` (already included in dependencies).

---

## Authentication

xdl authenticates using your browser cookies — no developer account or API key needed.

1. Open [x.com](https://x.com) and log in
2. Press **F12** → **Application** → **Cookies** → `https://x.com`
3. Copy the **Value** of these two cookies:

   | Cookie | Description |
   |--------|-------------|
   | `auth_token` | Login credential (~40 hex characters) |
   | `ct0` | CSRF token (~32 characters) |

> ⚠️ **Never share your cookies or commit them to a repository.**

---

## Configuration

### Option A: `.env` file (recommended)

Create a `.env` file in the project root (already in `.gitignore`):

```env
X_AUTH_TOKEN=your_auth_token
X_CT0=your_ct0

# Optional
X_OUTPUT_DIR=./downloads
X_CONCURRENCY=5
X_PROXY=http://127.0.0.1:7890
```

### Option B: CLI

```bash
xdl config --auth-token "..." --ct0 "..."
xdl config --auth-token "..." --ct0 "..." --proxy "http://127.0.0.1:7890"
```

Config is saved to `~/.x-downloader/config.json`.

> **Priority order:** Environment variables → `.env` → `~/.x-downloader/config.json`

### Option C: Browser auto-capture (experimental)

```bash
xdl config --login
```

Opens Chrome/Edge automatically and extracts cookies after login.

---

## Usage

### Download User Media

```bash
# Download all media from @username (incremental)
xdl user username

# Save to a specific directory (folder mode)
xdl user username --output ~/pictures

# Use SQLite single-file mode
xdl user username --mode sqlite --db ~/gallery.db

# Scan only the latest 100 tweets
xdl user username --limit 100

# Force full re-scan (ignore incremental records)
xdl user username --full

# Query the Media tab only (faster, server-side filtered)
xdl user username --media-only

# SQLite + Media tab combination (recommended)
xdl user username --media-only --db ~/gallery.db

# Images and GIFs only
xdl user username --image-only

# Videos only
xdl user username --video-only

# Reduce scan speed to avoid rate limiting (seconds)
xdl user username --scan-delay 2.0

# Debug mode (print API request details)
xdl user username --debug
```

> **About `--media-only`**: Uses X's `UserMedia` GraphQL endpoint (same as the profile Media tab). It filters out text-only tweets server-side, making pagination faster (~10 media items per page).  
> ⚠️ This endpoint **does not include retweet media**. Use normal mode (without `--media-only`) if you need retweet media.  
> Resume state is **independent** between the two modes — you can run both for the same user.

**Output path (folder mode):** `downloads/username_userID/tweetID_index.jpg`

### Download Liked Tweets

```bash
# Download all liked media (auto-detect your account)
xdl likes

# Specify username if auto-detection fails
xdl likes --me your_username

# Specify directory / limit count / specify database
xdl likes --output ~/pictures --limit 500
xdl likes --db ~/gallery.db

# Images and GIFs only
xdl likes --image-only

# Videos only
xdl likes --video-only
```

### Download a Single Tweet

```bash
# By tweet ID
xdl tweet 1234567890

# By tweet URL
xdl tweet https://x.com/user/status/1234567890

# Save to a SQLite database
xdl tweet 1234567890 --single --db ~/gallery.db
```

### Built-in Gallery Server

```bash
# Browse a SQLite gallery database
xdl serve gallery.db

# Specify port
xdl serve gallery.db --port 8080
```

A browser will automatically open at `http://localhost:<port>`. Right-click to delete media items.

### Other Commands

```bash
# Diagnose credentials and API connectivity
xdl doctor

# Show download statistics
xdl stats gallery.db

# Pre-generate video thumbnails (requires ffmpeg)
xdl thumbs gallery.db

# Import liked media from X data archive
xdl import-archive /path/to/archive --db gallery.db

# Convert between folder and SQLite storage modes
xdl convert ./downloads gallery.db
```

---

## Storage Modes

| | Folder Mode | SQLite Mode |
|-|-------------|-------------|
| Storage format | Directory tree | Single `.db` file |
| Direct access | ✅ Open with any image viewer | ❌ Requires `xdl serve` |
| Gallery | Basic HTML gallery | Full interactive gallery |
| Portability | Entire directory needed | Single file |
| Search / Delete | ❌ | ✅ Supported in gallery |

---

## Project Structure

```
x-downloader/
├── xdl/                        ← Python package
│   ├── __init__.py
│   ├── cli.py                  ← CLI entry point (registers all subcommands)
│   ├── _helpers.py             ← Shared utilities, constants, KVStore protocol
│   ├── commands/               ← Subcommand implementations (one file per command)
│   │   ├── config.py           ←   xdl config (incl. CDP browser login)
│   │   ├── user.py             ←   xdl user
│   │   ├── likes.py            ←   xdl likes
│   │   ├── tweet.py            ←   xdl tweet
│   │   ├── doctor.py           ←   xdl doctor
│   │   ├── gallery_cmd.py      ←   xdl gallery
│   │   ├── serve_cmd.py        ←   xdl serve
│   │   ├── convert.py          ←   xdl convert
│   │   ├── stats.py            ←   xdl stats
│   │   ├── thumbs.py           ←   xdl thumbs
│   │   └── archive.py          ←   xdl import-archive
│   ├── auth.py                 ← Request headers / cookie auth
│   ├── client.py               ← X GraphQL API client
│   ├── config.py               ← Config loading and persistence
│   ├── db.py                   ← Folder-mode download history DB (KVStore protocol)
│   ├── downloader.py           ← Async concurrent download engine (exponential backoff)
│   ├── gallery.py              ← HTML gallery generator
│   ├── media_parser.py         ← Tweet media parsing
│   ├── serve.py                ← Built-in HTTP gallery server
│   ├── store.py                ← SQLite media storage
│   ├── thumb.py                ← ffmpeg video thumbnail extraction
│   ├── archive.py              ← X data archive parser
│   └── _fetch_ids.py           ← Internal tool: extract Query IDs from X JS bundles
├── downloads/                  ← Default download directory (gitignored)
├── .env                        ← Credentials (gitignored)
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## Troubleshooting

| Error | Cause | Solution |
|-------|-------|----------|
| `401 Unauthorized` | Expired cookies | Re-copy `auth_token` and `ct0` from your browser |
| `403 Forbidden` | Invalid cookies | Make sure you copy from `x.com` (not `twitter.com`) |
| `503 Service Unavailable` | X server issue | Wait 30 seconds; auto-retries up to 8 times |
| Auto-detect account fails | `settings.json` API unavailable | Use `xdl likes --me your_username` |
| GraphQL request fails | Query ID has been updated | See below |
| `--media-only` returns nothing | Empty Media tab or rate limited | Check user has media; try without `--media-only` |

### Updating GraphQL Query IDs

When X updates its frontend and API requests start failing:

1. Run `python -m xdl._fetch_ids` to automatically scan for the latest IDs (requires a proxy)
2. Or check DevTools → Network, filter for `UserTweets` / `UserMedia` requests, and copy the ID from the URL
3. See also: [fa0311/TwitterInternalAPIDocument](https://github.com/fa0311/TwitterInternalAPIDocument) (auto-updated daily)

Then update the `query_ids` field in `~/.x-downloader/config.json`.

---

## Proxy Support

```env
# HTTP/HTTPS proxy (e.g., Clash)
X_PROXY=http://127.0.0.1:7890

# SOCKS5 proxy
X_PROXY=socks5://127.0.0.1:1080

# Authenticated proxy
X_PROXY=socks5://user:password@127.0.0.1:1080
```

---

## Contributing

Contributions are welcome! Feel free to open an issue or submit a pull request.

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes: `git commit -m 'Add some feature'`
4. Push to the branch: `git push origin feature/your-feature`
5. Open a Pull Request

---

## Disclaimer

- Cookies may expire over time (typically weeks to months)
- Keep concurrency reasonable (`X_CONCURRENCY`) to avoid rate limiting
- 429 / 5xx errors trigger automatic exponential-backoff retries (up to 3 times) and respect the `Retry-After` header
- This tool is intended for **personal use only**. Please comply with [X's Terms of Service](https://twitter.com/en/tos)

---

## License

MIT — see [LICENSE](LICENSE) for details.
