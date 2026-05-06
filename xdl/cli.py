"""X Image Downloader — CLI entry point."""
from __future__ import annotations

import sys

# Windows: switch console to UTF-8 so Rich can display Unicode (✓, ⠋, etc.)
if sys.platform == "win32":
    import ctypes
    ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    ctypes.windll.kernel32.SetConsoleCP(65001)

import click

from .commands.config import cmd_config
from .commands.user import cmd_user
from .commands.likes import cmd_likes
from .commands.tweet import cmd_tweet
from .commands.doctor import cmd_doctor
from .commands.gallery_cmd import cmd_gallery
from .commands.serve_cmd import cmd_serve
from .commands.convert import cmd_convert
from .commands.stats import cmd_stats
from .commands.thumbs import cmd_thumbs
from .commands.archive import cmd_import_archive


@click.group()
def cli() -> None:
    """X (Twitter) Image / GIF Downloader — powered by cookie auth."""


cli.add_command(cmd_config)
cli.add_command(cmd_user)
cli.add_command(cmd_likes)
cli.add_command(cmd_tweet)
cli.add_command(cmd_doctor)
cli.add_command(cmd_gallery)
cli.add_command(cmd_serve)
cli.add_command(cmd_convert)
cli.add_command(cmd_stats)
cli.add_command(cmd_thumbs)
cli.add_command(cmd_import_archive)


def main() -> None:
    """Installed CLI entry point."""
    cli()


if __name__ == "__main__":
    cli()
