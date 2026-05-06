"""'gallery' command — regenerate HTML gallery for an existing download directory."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import click

from .._helpers import console
from ..gallery import generate_gallery


@click.command("gallery")
@click.option("--output", default=None, help="Override output directory")
def cmd_gallery(output: Optional[str]) -> None:
    """(Re)generate the HTML gallery for an existing download directory.

    Scans OUTPUT_DIR for user subfolders and writes a single index.html.
    """
    from ..config import load_config
    cfg = load_config()
    output_dir = Path(output or cfg.get("output_dir", ""))
    if not output_dir or not output_dir.is_dir():
        console.print(
            "[red]✗ Output directory not found.[/red] "
            "Pass [bold]--output <dir>[/bold] or set a default with [bold]config --output[/bold]."
        )
        raise SystemExit(1)
    generate_gallery(output_dir)
