"""Video clip builder and index/time conversion utilities.

Concrete implementations use ``ffmpeg``/``ffprobe`` via subprocess so that the
tool execution layer does not require ``cv2``.  For tests without a real video
file, callers can subclass ``VideoClipBuilder`` or monkeypatch ``_probe_video`` /
``_run_ffmpeg``.
"""

from __future__ import annotations

import hashlib
import bisect
import json
import logging
import os
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Index / time conversion utilities
# ---------------------------------------------------------------------------
def _resolve_between_indices(fracture_between: list[int], num_frames: int) -> tuple[int, int]:
    """Validate and return ``(i, j)`` indices for ``fracture_between``."""
    if fracture_between is None or len(fracture_between) != 2:
        raise ValueError("fracture_between must be a two-element list")
    i, j = fracture_between
    if not (0 <= i < num_frames and 0 <= j < num_frames):
        raise ValueError("fracture_between indices are out of range")
    return i, j


def fracture_between_to_time_range(
    fracture_between: list[int],
    frames: list[dict[str, Any]],
) -> list[float]:
    """Map ``fracture_between = [i, j]`` to ``[frames[i].timestamp, frames[j].timestamp]``."""
    i, j = _resolve_between_indices(fracture_between, len(frames))
    return [frames[i]["timestamp"], frames[j]["timestamp"]]


def fracture_between_to_frame_range(
    fracture_between: list[int],
    frames: list[dict[str, Any]],
) -> list[int]:
    """Map ``fracture_between = [i, j]`` to ``[frames[i].original_frame, frames[j].original_frame]``."""
    i, j = _resolve_between_indices(fracture_between, len(frames))
    return [frames[i]["original_frame"], frames[j]["original_frame"]]


# ---------------------------------------------------------------------------
# ffmpeg helpers
# ---------------------------------------------------------------------------
def _which_ffmpeg() -> str:
    """Return the ffmpeg executable path or raise if unavailable."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError(
            "ffmpeg executable not found. Install ffmpeg to use the concrete "
            "VideoClipBuilder implementations."
        )
    return ffmpeg


def _which_ffprobe() -> str:
    """Return the ffprobe executable path or raise if unavailable."""
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        raise RuntimeError(
            "ffprobe executable not found. Install ffmpeg to use the concrete "
            "VideoClipBuilder implementations."
        )
    return ffprobe


def _probe_video(video_path: str) -> dict[str, Any]:
    """Probe a video file and return fps, total_frames, duration and width/height."""
    ffprobe = _which_ffprobe()
    cmd = [
        ffprobe,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate,avg_frame_rate,nb_frames,duration,width,height",
        "-show_entries", "format=duration",
        "-of", "json",
        video_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(proc.stdout)

    streams = data.get("streams", [])
    fmt = data.get("format", {})
    if not streams:
        raise ValueError(f"No video stream found in {video_path}")
    stream = streams[0]

    fps = _parse_fps(stream.get("r_frame_rate") or stream.get("avg_frame_rate", "0/1"))
    duration = _parse_float(stream.get("duration") or fmt.get("duration"))
    total_frames = _parse_int(stream.get("nb_frames"))

    return {
        "fps": fps,
        "total_frames": total_frames or 0,
        "duration": duration or 0.0,
        "width": _parse_int(stream.get("width")) or 0,
        "height": _parse_int(stream.get("height")) or 0,
    }


def _probe_frame_timestamps(video_path: str) -> list[float]:
    """Return decoded video-frame timestamps reported by ffprobe."""
    proc = subprocess.run(
        [
            _which_ffprobe(),
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "frame=best_effort_timestamp_time",
            "-of", "json",
            video_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    values: list[float] = []
    for frame in json.loads(proc.stdout).get("frames", []):
        timestamp = _parse_float(frame.get("best_effort_timestamp_time"))
        if timestamp is not None:
            values.append(timestamp)
    if not values:
        raise RuntimeError(f"ffprobe did not return frame timestamps for {video_path}")
    return values


def _nearest_timestamp_index(timestamps: list[float], target: float) -> int:
    """Return the closest actual frame index for ``target``."""
    pos = bisect.bisect_left(timestamps, target)
    if pos <= 0:
        return 0
    if pos >= len(timestamps):
        return len(timestamps) - 1
    before = timestamps[pos - 1]
    after = timestamps[pos]
    return pos - 1 if target - before <= after - target else pos


def _sha256_file(path: str) -> str:
    """Return the SHA256 hex digest of the file at ``path``."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_fps(fps_str: str) -> float:
    """Parse ffmpeg fps expressions like ``30000/1001``."""
    if not fps_str:
        return 0.0
    parts = fps_str.split("/")
    if len(parts) == 2:
        try:
            num, den = float(parts[0]), float(parts[1])
            return num / den if den else 0.0
        except (TypeError, ValueError):
            return 0.0
    try:
        return float(fps_str)
    except (TypeError, ValueError):
        return 0.0


def _run_ffmpeg(args: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run ffmpeg with the given arguments."""
    ffmpeg = _which_ffmpeg()
    return subprocess.run([ffmpeg, *args], capture_output=True, text=True, check=check)


# ---------------------------------------------------------------------------
# Temporary clip result
# ---------------------------------------------------------------------------
@dataclass
class ClipBuildResult:
    """Path to a continuous temporary MP4 clip plus its frame manifest.

    The ``manifest`` maps each frame index inside the temporary clip back to
    the corresponding original video frame number and timestamp.  It is the
    authoritative source for translating model-output ``fracture_between``
    indices into original-video time ranges.

    ``file_hash`` is the SHA256 hex digest of the temporary clip file and
    ``file_size`` is its size in bytes.  Both are computed by
    ``FfmpegVideoClipBuilder.build_with_manifest`` for diagnostics.
    """

    path: str
    manifest: list[dict[str, Any]]
    file_hash: str = ""
    file_size: int = 0


# ---------------------------------------------------------------------------
# VideoClipBuilder
# ---------------------------------------------------------------------------
class VideoClipBuilder(ABC):
    """Abstract builder for temporary inference ``.mp4`` clips."""

    @abstractmethod
    def build(
        self,
        source_video: str,
        sample_range: list[float],
    ) -> str:
        """Return the path of the temporary clip sent to ``InferenceClient``."""
        ...


class FfmpegVideoClipBuilder(VideoClipBuilder):
    """Build continuous temporary inference clips by cropping the source video.

    The builder no longer pre-extracts frames or concatenates them at an
    artificial FPS.  Instead it directly crops the original video between
    ``sample_range[0]`` and ``sample_range[1]`` and preserves the original
    time axis.  A manifest is produced that maps every frame in the temporary
    clip back to the original video frame index and timestamp.

    For ``adaptive`` strategy the builder falls back to ``uniform`` because
    the contract only supports continuous cropping for this version.

    The ``frames`` argument of ``build`` is kept for backward compatibility
    but is intentionally ignored; the clip is derived solely from
    ``sample_range``.
    """

    def __init__(self, output_dir: str | None = None) -> None:
        self.output_dir = output_dir

    def build_with_manifest(
        self,
        source_video: str,
        sample_range: list[float],
    ) -> ClipBuildResult:
        """Crop a continuous MP4 clip and return it with its frame manifest.

        The manifest is based on decoded frame PTS, never theoretical FPS.
        """
        if not os.path.exists(source_video):
            raise FileNotFoundError(f"Source video not found: {source_video}")

        probe = _probe_video(source_video)
        duration = probe["duration"]

        # Explicit validation to avoid cryptic ffmpeg failures on degenerate ranges.
        if len(sample_range) != 2:
            raise ValueError("sample_range must be a two-element list [start, end]")
        start, end = sample_range
        if not (0 <= start < end <= duration):
            raise ValueError(
                f"Invalid sample_range [{start}, {end}]: expected "
                f"0 <= start < end <= video_duration ({duration})"
            )

        start = max(0.0, start)
        end = min(end, duration) if duration else end
        if end < start:
            end = start
        clip_duration = end - start

        out_dir = Path(self.output_dir) if self.output_dir else Path("data/08_runtime/agent_clips")
        out_dir.mkdir(parents=True, exist_ok=True)

        video_stem = Path(source_video).stem
        output_path = out_dir / f"{video_stem}_{start:.2f}_{end:.2f}.mp4"

        # Directly crop the continuous segment.  Do NOT pre-extract frames.
        _run_ffmpeg(
            [
                "-y",
                "-ss", str(start),
                "-i", source_video,
                "-t", str(clip_duration),
                "-an",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                str(output_path),
            ]
        )

        source_timestamps = _probe_frame_timestamps(source_video)
        temp_timestamps = _probe_frame_timestamps(str(output_path))
        temp_origin = temp_timestamps[0]

        # Build manifest from actual decoded PTS. The temporary clip's first
        # PTS can be non-zero, so normalize it before mapping to source time.
        manifest: list[dict[str, Any]] = []
        for k, temp_timestamp in enumerate(temp_timestamps):
            target_timestamp = start + (temp_timestamp - temp_origin)
            original_frame = _nearest_timestamp_index(source_timestamps, target_timestamp)
            timestamp = source_timestamps[original_frame]
            if timestamp > end + 1e-6:
                break
            manifest.append(
                {
                    "temp_index": k,
                    "clip_timestamp": round(temp_timestamp, 6),
                    "original_frame": original_frame,
                    "timestamp": round(timestamp, 6),
                }
            )

        file_size = output_path.stat().st_size
        file_hash = _sha256_file(str(output_path))
        return ClipBuildResult(
            path=str(output_path),
            manifest=manifest,
            file_hash=file_hash,
            file_size=file_size,
        )

    def build(
        self,
        source_video: str,
        sample_range: list[float],
    ) -> str:
        """Return the path of the continuous temporary clip."""
        result = self.build_with_manifest(
            source_video=source_video,
            sample_range=sample_range,
        )
        return result.path


VideoClipBuilder.register(FfmpegVideoClipBuilder)
