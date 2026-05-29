# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added

- Gallery favorites (收藏夹): favorite individual media (images/videos) from the
  grid (hover ♥) or the lightbox, and browse them in a cross-user **❤️ 收藏夹**
  view from the top bar (with a live count badge). Favorites persist in
  `localStorage` (`xgallery_favorites_v1`) as self-contained snapshots, so they
  work in all gallery modes — including the offline folder/`file://` build —
  independently of lazy-loaded `serve` data, and survive page reloads. The
  favorites view reuses the same virtual-scroll grid + lightbox (sort/filter
  apply), with history/hash support (`#favorites`). The favorites view also
  offers a **按用户分组** layout mode (in addition to the default 平铺 grid)
  that renders one section per user with a clickable @handle header; the
  chosen layout is remembered in `localStorage`.
- `xdl update-ids` — fetch the latest GraphQL query IDs from X's web client and
  save them to the config in one step. Supports `--dry-run` (preview a diff
  table without writing), `--proxy`, `-y/--yes`, and `--debug`. Replaces the
  manual `python -m xdl._fetch_ids` → copy → `xdl config --query-id` workflow.

### Fixed

- `xdl thumbs`: fixed several thread-pool issues. (1) Worker threads each opened
  a per-thread SQLite connection that was never closed, leaking connections and
  leaving `-wal`/`-shm` files un-checkpointed after a run; the store now tracks
  every connection and closes them via `SQLiteStore.close_all()` once the pool
  finishes. (2) Replaced submit-all-at-once with a bounded in-flight window
  (`workers × 2`) so peak memory no longer scales with library size — only a
  handful of full media BLOBs are held at a time. (3) `--workers` is clamped to
  at least 1, so `--workers 0`/negative no longer crashes `ThreadPoolExecutor`.
- Gallery virtual scroll: pin the media grid and card grid to the JS-computed
  column count (`grid-template-columns: repeat(N,1fr)`) so CSS `auto-fill` can no
  longer disagree with the virtual-scroll math, and reserve the viewport
  scrollbar gutter (`html { scrollbar-gutter: stable; overflow-y: scroll }`) so
  the content width — and therefore the computed column count `N` — stays
  constant whether or not the vertical scrollbar is visible. Together these fix
  images drifting sideways (e.g. shifting from the 3rd to the 2nd column) and the
  whole grid reflowing while scrolling large galleries in `xdl serve`.

### Changed

- Merged the ~90% duplicated scan-and-download logic of the `user` and `likes`
  commands into a shared `xdl/commands/_feed.py` driver (`run_feed` + `FeedSpec`).
  `user.py` (317→117 lines) and `likes.py` (317→125 lines) now only perform
  account/user resolution and describe their per-command differences (feed mode,
  download mode, output folder, status label, iterator). Behaviour is unchanged.
- Refactored the gallery frontend out of the 1557-line `xdl/gallery.py`
  monolith: the CSS, JavaScript and HTML skeleton now live as standalone files
  under `xdl/static/` (`gallery.css`, `gallery.js`, `gallery.html`) with no
  Python brace-escaping. `build_gallery_html` reads them and injects the dynamic
  values via token replacement. The generated gallery HTML is byte-for-byte
  identical to before in folder, serve and API modes.
- The `serve` gallery now streams media from SQLite in 1 MB chunks (via SQLite
  `substr`) instead of loading the entire BLOB into memory per request. Large
  videos — and their frequent HTTP Range requests during seeking — no longer
  spike server memory. Range/206, full/200, `Accept-Ranges`, `ETag`/304 and
  `Cache-Control` behaviour are unchanged.
- `xdl._fetch_ids.fetch_ids` now accepts an optional progress callback and also
  scans for the `UserMedia` query ID.
- Stale-query-ID failures are now actionable: a 400/404 from any GraphQL endpoint
  fails fast with a `RuntimeError` pointing to `xdl update-ids` (previously it
  retried 8× over ~6 minutes before crashing). `xdl doctor` now flags 400/404 the
  same way and its tip references `xdl update-ids` instead of the old script.

---

## [0.2.0] — 2024-12-01

### Changed

- Reorganized all source files into a proper `xdl/` Python package
- `main.py` renamed to `xdl/cli.py`; all cross-module imports converted to relative imports
- `pyproject.toml` now uses `[tool.setuptools.packages.find]` instead of flat `py-modules`
- Updated `pyproject.toml` with classifiers, keywords, and project URLs
- Rewrote `README.md` with full feature table, usage examples, and project structure

### Fixed

- Phase 1 → Phase 2 Dynamic Island toast animation now morphs the container directly
  (height + border-radius transition on `#toast-box`) instead of scale-collapse/expand

---

## [0.1.0] — 2024-11-01

### Added

- `xdl user <username>` — download all media from a user's tweets
- `xdl likes` — download media from liked tweets, organized by original author
- Two storage modes: `folder` (file tree) and `sqlite` (single `.db` file)
- Incremental download: only fetches new content on subsequent runs
- Resume support: Ctrl+C saves progress; next run continues from the same point
- `xdl serve <db>` — built-in HTTP gallery server with virtual scroll and lightbox
- `xdl gallery` — generate static HTML gallery for folder mode
- `xdl stats <db>` — show download statistics
- `xdl thumbs <db>` — pre-generate video thumbnails via ffmpeg
- `xdl import-archive` — import liked media from X data archive (`like.js`)
- `xdl convert` — convert between folder and SQLite storage modes
- `xdl doctor` — diagnose credentials and API connectivity
- `xdl config --login` — capture auth cookies via Chrome/Edge CDP
- Right-click context menu in gallery: delete user or individual media items
- Two-phase "Dynamic Island" delete toast: confirmation card → undo pill with 5 s countdown
- Proxy support: HTTP/HTTPS and SOCKS5

[Unreleased]: https://github.com/yourusername/x-downloader/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/yourusername/x-downloader/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/yourusername/x-downloader/releases/tag/v0.1.0
