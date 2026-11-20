"""Stage 4A tests: pure runtime_guards and sampling run_id isolation / PTS caching."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.runtime_guards import (
    evaluate_unrecognized_reason,
    has_complete_no_fracture_coverage,
    has_consistent_special_recheck,
)
from agent.sampling import FfmpegVideoClipBuilder


def test_runtime_guards_pure_v4_1_coverage_and_special_recheck() -> None:
    history = [
        {
            "result": {
                "ok": True,
                "sample_range": [0.0, 40.0],
                "model_output": {"clip_state": "未断裂", "special_case": None},
            }
        },
        *[
            {
                "result": {
                    "ok": True,
                    "sample_range": rng,
                    "model_output": {"clip_state": "未断裂", "special_case": None},
                }
            }
            for rng in (
                [0.0, 10.0],
                [7.5, 17.5],
                [15.0, 25.0],
                [22.5, 32.5],
                [30.0, 40.0],
            )
        ],
    ]
    assert (
        has_complete_no_fracture_coverage(
            history,
            duration=40.0,
            visual_contract_version="tensile-vlm/v4.1",
            coverage_start_index=0,
        )
        is True
    )
    assert (
        has_complete_no_fracture_coverage(
            history,
            duration=40.0,
            visual_contract_version="tensile-vlm/v4.1",
            coverage_start_index=None,
        )
        is False
    )

    fracture_history = [
        {
            "result": {
                "ok": True,
                "sample_range": [10.0, 20.0],
                "model_output": {"clip_state": "发生断裂", "special_case": None},
            }
        },
        {
            "result": {
                "ok": True,
                "sample_range": [10.0, 20.0],
                "model_output": {"clip_state": "发生断裂", "special_case": None},
            }
        },
    ]
    assert (
        has_consistent_special_recheck(
            fracture_history,
            reason="video_anomaly",
            visual_contract_version="tensile-vlm/v4.1",
        )
        is False
    )

    allowed, _ = evaluate_unrecognized_reason(
        "max_rounds",
        history=[],
        round_idx=0,
        max_rounds=10,
        conflict_count=0,
        unresolved_conflict=False,
        visual_contract_version="tensile-vlm/v4.1",
    )
    assert allowed is False


def test_sampling_caches_source_pts_and_isolates_paths_by_run_id(
    tmp_path: Path,
) -> None:
    dir_a = tmp_path / "dir_a"
    dir_b = tmp_path / "dir_b"
    dir_a.mkdir()
    dir_b.mkdir()
    video_a = dir_a / "same_name.mp4"
    video_b = dir_b / "same_name.mp4"
    video_a.write_bytes(b"video-a")
    video_b.write_bytes(b"video-b")

    source_pts = [round(i * 0.1, 6) for i in range(101)]
    probe_video_calls: list[str] = []
    probe_pts_calls: list[str] = []

    def fake_probe_video(path: str) -> dict:
        probe_video_calls.append(path)
        return {"fps": 10.0, "total_frames": 101, "duration": 10.0, "width": 64, "height": 64}

    def fake_probe_pts(path: str) -> list[float]:
        probe_pts_calls.append(path)
        if Path(path).resolve() in {video_a.resolve(), video_b.resolve()}:
            return list(source_pts)
        return [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]

    def fake_run_ffmpeg(args: list[str], check: bool = True) -> MagicMock:
        del check
        out = Path(args[-1])
        out.write_bytes(f"clip:{out.name}".encode("utf-8"))
        return MagicMock(returncode=0)

    builder = FfmpegVideoClipBuilder(output_dir=str(tmp_path / "clips"), run_id="run-001")
    with (
        patch("agent.sampling._probe_video", side_effect=fake_probe_video),
        patch("agent.sampling._probe_frame_timestamps", side_effect=fake_probe_pts),
        patch("agent.sampling._run_ffmpeg", side_effect=fake_run_ffmpeg),
    ):
        clip_1 = builder.build_with_manifest(str(video_a), [1.001, 2.001])
        clip_2 = builder.build_with_manifest(str(video_a), [1.004, 2.004])
        clip_3 = builder.build_with_manifest(str(video_b), [1.001, 2.001])

    # Source video_a probed only once across two clips
    assert probe_video_calls.count(str(video_a)) == 1
    assert probe_pts_calls.count(str(video_a)) == 1
    # All three output paths are distinct and under run-001/
    paths = {clip_1.path, clip_2.path, clip_3.path}
    assert len(paths) == 3
    assert all("/run-001/" in p or "\\run-001\\" in p for p in paths)
    # Identical frame manifests for identical ranges
    assert clip_1.manifest == clip_3.manifest
