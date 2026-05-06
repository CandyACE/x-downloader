# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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

