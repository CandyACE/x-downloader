"""Video thumbnail extraction via ffmpeg (pipe mode, no temp files)."""
from __future__ import annotations

import subprocess


def extract_frame(video_bytes: bytes, *, width: int = 400) -> bytes | None:
    """
    Extract the first keyframe from *video_bytes* and return it as JPEG bytes.

    Uses ffmpeg with stdin/stdout pipes — no temp files are written.
    Returns ``None`` if ffmpeg is not available or extraction fails.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", "pipe:0",
        "-vframes", "1",
        "-vf", f"scale={width}:-2",   # resize to width, keep aspect ratio
        "-f", "image2",
        "-vcodec", "mjpeg",
        "pipe:1",
    ]
    try:
        result = subprocess.run(
            cmd,
            input=video_bytes,
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None
