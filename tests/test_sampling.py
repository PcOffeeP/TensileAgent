from __future__ import annotations

import pytest

from agent.sampling import (
    ClipBuildResult,
    fracture_between_to_frame_range,
    fracture_between_to_time_range,
)


def test_fracture_between_to_time_range():
    frames = [
        {"input_index": 0, "original_frame": 100, "timestamp": 0.0},
        {"input_index": 1, "original_frame": 108, "timestamp": 1.0},
        {"input_index": 2, "original_frame": 116, "timestamp": 2.0},
    ]
    assert fracture_between_to_time_range([1, 2], frames) == [1.0, 2.0]
    assert fracture_between_to_frame_range([0, 1], frames) == [100, 108]


def test_fracture_between_out_of_range():
    frames = [
        {"input_index": 0, "original_frame": 100, "timestamp": 0.0},
    ]
    with pytest.raises(ValueError):
        fracture_between_to_time_range([0, 1], frames)


def test_clip_build_result_includes_hash_and_size(tmp_path, monkeypatch):
    """ClipBuildResult must carry SHA256 hash and byte size of the temp clip."""
    from agent.sampling import FfmpegVideoClipBuilder, _probe_video

    source = tmp_path / "src.mp4"
    source.write_bytes(b"\x00\x00\x00\x18ftypisom\x00\x00\x00\x00isommp41fake_video")

    def fake_probe(path):
        return {"fps": 8.0, "total_frames": 8, "duration": 1.0, "width": 64, "height": 64}

    def fake_ffmpeg(args, check=True):
        output = args[-1]
        # Copy source bytes to the output path so hashing/sizing works.
        import shutil
        shutil.copy(str(source), output)
        return None

    monkeypatch.setattr("agent.sampling._probe_video", fake_probe)
    monkeypatch.setattr(
        "agent.sampling._probe_frame_timestamps",
        lambda path: [i / 8 for i in range(8)],
    )
    monkeypatch.setattr("agent.sampling._run_ffmpeg", fake_ffmpeg)

    builder = FfmpegVideoClipBuilder(output_dir=str(tmp_path / "clips"))
    result = builder.build_with_manifest(str(source), [0.0, 1.0])

    assert isinstance(result, ClipBuildResult)
    assert result.file_size == source.stat().st_size
    import hashlib
    assert result.file_hash == hashlib.sha256(source.read_bytes()).hexdigest()
    assert result.file_hash != ""
