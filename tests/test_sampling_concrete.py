from __future__ import annotations

import os
import subprocess

import pytest

from agent.sampling import (
    ClipBuildResult,
    FfmpegVideoClipBuilder,
    _parse_fps,
    _probe_video,
)


@pytest.fixture(scope="session")
def synthetic_video(tmp_path_factory):
    """Create a small 10s 30fps synthetic video via ffmpeg."""
    path = tmp_path_factory.mktemp("videos") / "synthetic_10s_30fps.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", "testsrc=size=320x240:rate=30:duration=10",
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        str(path),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return str(path)


def test_probe_video(synthetic_video):
    probe = _probe_video(synthetic_video)
    assert probe["fps"] == pytest.approx(30.0, abs=0.1)
    assert probe["duration"] == pytest.approx(10.0, abs=0.2)
    assert probe["total_frames"] == pytest.approx(300, abs=5)


def test_parse_fps_fraction():
    assert _parse_fps("30000/1001") == pytest.approx(29.97, abs=0.01)


def test_ffmpeg_clip_builder_crops_continuously(synthetic_video, tmp_path):
    """The builder must crop a continuous segment, not pre-extract frames."""
    builder = FfmpegVideoClipBuilder(output_dir=str(tmp_path / "clips"))
    clip_path = builder.build(
        source_video=synthetic_video,
        sample_range=[2.0, 4.0],
    )
    assert clip_path.endswith(".mp4")
    probe = _probe_video(clip_path)
    # The clip preserves the source time axis: 2 seconds at 30 fps = 60 frames.
    assert probe["total_frames"] == pytest.approx(60, abs=2)
    assert probe["duration"] == pytest.approx(2.0, abs=0.2)
    assert probe["fps"] == pytest.approx(30.0, abs=0.5)


def test_ffmpeg_clip_builder_with_manifest(synthetic_video, tmp_path):
    """build_with_manifest returns a ClipBuildResult with a valid frame manifest."""
    builder = FfmpegVideoClipBuilder(output_dir=str(tmp_path / "clips"))
    result = builder.build_with_manifest(
        source_video=synthetic_video,
        sample_range=[2.0, 4.0],
    )
    assert isinstance(result, ClipBuildResult)
    assert result.path.endswith(".mp4")
    assert os.path.exists(result.path)

    manifest = result.manifest
    # 2 seconds of 30 fps video -> 60 frames (allow tiny container variance).
    assert len(manifest) == pytest.approx(60, abs=2)
    assert manifest[0]["temp_index"] == 0
    assert manifest[0]["timestamp"] == pytest.approx(2.0, abs=0.02)
    assert manifest[0]["original_frame"] == pytest.approx(60, abs=1)
    assert manifest[-1]["timestamp"] < 4.0 + 0.1
    # Manifest indices must be contiguous and monotonic.
    for i, entry in enumerate(manifest):
        assert entry["temp_index"] == i
        assert entry["original_frame"] == pytest.approx(
            round(entry["timestamp"] * 30.0), abs=1
        )


def test_ffmpeg_clip_builder_has_no_legacy_sampling_knobs(synthetic_video, tmp_path):
    """The public builder only accepts source video and sample range."""
    builder = FfmpegVideoClipBuilder(output_dir=str(tmp_path / "clips"))
    clip_path = builder.build(
        source_video=synthetic_video,
        sample_range=[2.0, 4.0],
    )
    probe = _probe_video(clip_path)
    # A 2-second continuous crop at 30 fps has ~60 frames, not 3.
    assert probe["total_frames"] == pytest.approx(60, abs=2)


@pytest.mark.parametrize(
    "sample_range, expected_substring",
    [
        ([5.0, 5.0], "0 <= start < end"),  # zero-length range
        ([-1.0, 3.0], "0 <= start"),  # negative start
        ([5.0, 15.0], "end <= video_duration"),  # end beyond video duration
        ([7.0, 3.0], "start < end"),  # inverted range
        ([1.0], "two-element list"),  # malformed range
    ],
)
def test_ffmpeg_clip_builder_rejects_invalid_sample_range(
    synthetic_video, tmp_path, sample_range, expected_substring
):
    """Degenerate or out-of-bounds sample_range must raise a clear ValueError."""
    builder = FfmpegVideoClipBuilder(output_dir=str(tmp_path / "clips"))
    with pytest.raises(ValueError, match=expected_substring):
        builder.build_with_manifest(
            source_video=synthetic_video,
            sample_range=sample_range,
        )
