import json
from pathlib import Path

from agent.acceptance_reporting import (
    build_diagnostic_report,
    summarize_batch_timing,
)


def test_diagnostic_report_exposes_confusions_and_failure_index() -> None:
    records = [
        (
            {
                "video_id": "fracture",
                "has_fracture": True,
                "fracture_time": 2.0,
                "duration": 10.0,
                "fracture_mechanism": "脆性断裂",
                "fracture_site": "inside_gauge",
                "special_case": None,
            },
            {
                "video_id": "fracture",
                "status": "fracture",
                "has_fracture": True,
                "time_range": [1.0, 3.0],
                "fracture_type": "韧性断裂",
                "location": "inside_gauge",
            },
        ),
        (
            {
                "video_id": "special",
                "has_fracture": None,
                "fracture_time": None,
                "duration": 10.0,
                "fracture_mechanism": None,
                "fracture_site": None,
                "special_case": "未夹紧",
            },
            {
                "video_id": "special",
                "status": "no_fracture",
                "has_fracture": False,
                "special_case": None,
            },
        ),
    ]
    report = build_diagnostic_report(records)
    assert report["presence_confusion_matrix"]["fracture"]["fracture"] == 1
    assert report["mechanism_confusion_matrix"]["脆性断裂"]["韧性断裂"] == 1
    assert report["failure_sample_index"] == [
        {"video_id": "fracture", "failed_components": ["mechanism"]},
        {"video_id": "special", "failed_components": ["special_case"]},
    ]


def test_timing_report_uses_recorded_batch_boundaries(tmp_path: Path) -> None:
    values = {
        "a": ("2026-01-01T00:00:00+00:00", "2026-01-01T00:00:02+00:00"),
        "b": ("2026-01-01T00:00:01+00:00", "2026-01-01T00:00:05+00:00"),
    }
    for video_id, (started, finished) in values.items():
        task = tmp_path / video_id
        task.mkdir()
        (task / "result.json").write_text(
            json.dumps({"started_at": started, "finished_at": finished}),
            encoding="utf-8",
        )
    report = summarize_batch_timing(tmp_path, set(values))
    assert report["wall_seconds"] == 5.0
    assert report["wall_throughput_videos_per_second"] == 0.4
    assert report["task_duration_seconds"]["median"] == 2.0
    assert report["task_duration_seconds"]["p95"] == 4.0
