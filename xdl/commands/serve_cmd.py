"""'serve' command — start local HTTP server to browse a gallery."""
from __future__ import annotations

import click


@click.command("serve")
@click.argument("path")
@click.option("--port", default=0, type=int, help="Port to listen on (0 = auto)")
def cmd_serve(path: str, port: int) -> None:
    """Start a local HTTP server to browse a gallery.

    PATH can be:
      - a .db file (SQLite mode) — images are served from the database
      - a directory containing index.html (folder mode) — static file serving
    """
    from ..serve import serve
    serve(path, port=port)
