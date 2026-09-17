"""Locally-generated MP4 fixtures for Task 3.1 tests.

All fixtures are synthesized at test time with ffmpeg's `lavfi` virtual
inputs (testsrc/sine) -- no binary media files are committed, and no
network access or real camera/microphone capture is required.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def make_video_with_audio(path: Path, duration: float, size: str = "64x64", rate: int = 5) -> Path:
    """A synthetic video with both a video and an audio (sine tone) stream."""

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration}:size={size}:rate={rate}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=1000:duration={duration}",
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            str(path),
        ],
        check=True,
    )
    return path


def make_video_without_audio(path: Path, duration: float, size: str = "64x64", rate: int = 5) -> Path:
    """A synthetic video with a video stream only -- no audio track at all."""

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={duration}:size={size}:rate={rate}",
            "-c:v",
            "libx264",
            "-an",
            str(path),
        ],
        check=True,
    )
    return path


def make_corrupt_video(path: Path) -> Path:
    """A file with an .mp4 extension that is not valid media data at all."""

    path.write_bytes(b"This is not a real MP4 file, just plain text bytes.")
    return path
