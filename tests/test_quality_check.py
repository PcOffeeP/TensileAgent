from __future__ import annotations

import json
from pathlib import Path

import pytest

from pipeline.scripts.quality_check import (
    FRACTURE_TYPES,
    LEGAL_COMBINATIONS,
    TRUTH_FIELDS,
    _matches_legal_combination,
    main,
    run_quality_check,
)


def _make_sample(
    sample_id: str = "video_0001_full",
    source_video: str = "video_0001",
    has_fracture: bool | None = True,
    fracture_between: list[int] | None = None,
    ftype: str = "韧性断裂",
    location: str | None = "inside_gauge",
    frame_count: int = 8,
    video_path: str = "data/01_videos/video_0001.mp4",
    fingerprint: str = "processor:v2:stable",
) -> dict:
    if fracture_between is None and has_fracture is True and ftype in FRACTURE_TYPES:
        fracture_between = [frame_count - 2, frame_count - 1]
    output = {
        "has_fracture": has_fracture,
        "fracture_between": fracture_between,
        "type": ftype,
        "location": location,
        "confidence": 0.95,
    }
    mapping = [{"input_index": i, "original_frame": i * 10} for i in range(frame_count)]
    return {
        "id": sample_id,
        "videos": [video_path],
        "messages": [
            {"role": "system", "content": "system prompt"},
            {"role": "user", "content": "user prompt"},
            {"role": "assistant", "content": json.dumps(output, ensure_ascii=False)},
        ],
        "has_fracture": has_fracture,
        "has_fracture_canonical": has_fracture,
        "fracture_between": fracture_between,
        "type": ftype,
        "location": location,
        "location_canonical": location,
        "source_type": ftype,
        "source_location": location,
        "source_video": source_video,
        "start_frame": 0,
        "end_frame": 100,
        "actual_frame_mapping": mapping,
        "processor_fingerprint": fingerprint,
    }


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def fake_project(tmp_path: Path) -> Path:
    """创建包含最小合法 v2 产物的临时项目目录。"""
    videos_dir = tmp_path / "data" / "01_videos"
    videos_dir.mkdir(parents=True)
    video_ids = [f"video_{i:04d}" for i in range(1, 15)] + ["video_0100"]
    for vid in video_ids:
        (videos_dir / f"{vid}.mp4").write_bytes(b"fake")

    merged_dir = tmp_path / "data" / "06_merged"
    merged_dir.mkdir(parents=True)

    def pos(vid: str, sid: str) -> dict:
        return _make_sample(sid, vid, True, [6, 7], "韧性断裂", "inside_gauge")

    def neg(vid: str, sid: str, ftype: str = "未断裂") -> dict:
        return _make_sample(sid, vid, False, None, ftype, None)

    # 各 split 使用互不重叠的 source_video
    _write_json(merged_dir / "fold_0_train.json", [pos("video_0001", "t0_1"), pos("video_0002", "t0_2"), neg("video_0003", "t0_3"), neg("video_0004", "t0_4")])
    _write_json(merged_dir / "fold_0_val.json", [pos("video_0005", "v0_1"), neg("video_0006", "v0_2")])
    _write_json(merged_dir / "fold_1_train.json", [pos("video_0007", "t1_1"), pos("video_0008", "t1_2"), neg("video_0009", "t1_3"), neg("video_0010", "t1_4")])
    _write_json(merged_dir / "fold_1_val.json", [pos("video_0011", "v1_1")])
    _write_json(merged_dir / "fold_2_train.json", [pos("video_0012", "t2_1"), pos("video_0013", "t2_2"), neg("video_0014", "t2_3")])
    _write_json(merged_dir / "fold_2_val.json", [neg("video_0004", "v2_1", "未夹紧")])

    test_inputs = [
        {"id": "video_0100", "video_id": "video_0100", "video_path": "data/01_videos/video_0100.mp4"}
    ]
    _write_json(merged_dir / "test_inputs.json", test_inputs)

    _write_json(
        merged_dir / "samples_meta.json",
        {"total_samples": 15, "total_video_sources": 14, "total_positive": 9, "total_negative": 6},
    )

    subvideos_meta = tmp_path / "data" / "07_metadata" / "subvideos_meta.json"
    subvideos_meta.parent.mkdir(parents=True, exist_ok=True)
    _write_json(
        subvideos_meta,
        {
            "subvideos": [],
            "candidates": [],
            "exclusions": [
                {"reason": "duration_too_short", "source_video": "video_0001"},
            ],
            "exclusion_stats": {},
        },
    )
    return tmp_path


class TestMatchesLegalCombination:
    def test_normal_fracture_passes(self):
        assert _matches_legal_combination(
            {
                "has_fracture": True,
                "fracture_between": [3, 4],
                "type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.9,
            }
        )

    def test_no_fracture_passes(self):
        assert _matches_legal_combination(
            {
                "has_fracture": False,
                "fracture_between": None,
                "type": "未断裂",
                "location": None,
                "confidence": 0.9,
            }
        )

    def test_video_anomaly_unknown_passes(self):
        assert _matches_legal_combination(
            {
                "has_fracture": None,
                "fracture_between": None,
                "type": "视频异常",
                "location": None,
                "confidence": 0.7,
            }
        )

    def test_video_anomaly_fracture_passes(self):
        assert _matches_legal_combination(
            {
                "has_fracture": True,
                "fracture_between": None,
                "type": "视频异常",
                "location": None,
                "confidence": 0.65,
            }
        )

    def test_illegal_combination_fails(self):
        # has_fracture=true but fracture_between present for non-fracture type
        assert not _matches_legal_combination(
            {
                "has_fracture": True,
                "fracture_between": [3, 4],
                "type": "未断裂",
                "location": None,
                "confidence": 0.9,
            }
        )

    def test_missing_confidence_fails(self):
        assert not _matches_legal_combination(
            {
                "has_fracture": False,
                "fracture_between": None,
                "type": "未断裂",
                "location": None,
            }
        )


class TestQualityCheck:
    def test_legal_pass(self, fake_project: Path, capsys):
        merged_dir = fake_project / "data" / "06_merged"
        report_path = fake_project / "quality_check_report.json"
        errors, warnings, summary = run_quality_check(
            merged_dir=merged_dir,
            subvideos_meta_path=fake_project / "data" / "07_metadata" / "subvideos_meta.json",
            report_path=report_path,
            project_root=fake_project,
        )
        assert errors == []
        assert summary["error_count"] == 0
        assert report_path.exists()

    def test_illegal_field_combination_reported(self, fake_project: Path):
        merged_dir = fake_project / "data" / "06_merged"
        bad_sample = _make_sample(
            "bad", "video_0001", has_fracture=True, fracture_between=[6, 7], ftype="未断裂", location=None
        )
        _write_json(merged_dir / "fold_0_train.json", [bad_sample])
        errors, _warnings, _summary = run_quality_check(
            merged_dir=merged_dir,
            subvideos_meta_path=fake_project / "data" / "07_metadata" / "subvideos_meta.json",
            report_path=fake_project / "report.json",
            project_root=fake_project,
        )
        assert any(e["check"] == "field_combination" for e in errors)

    def test_invalid_type_reported(self, fake_project: Path):
        merged_dir = fake_project / "data" / "06_merged"
        bad_sample = _make_sample(
            "bad", "video_0001", has_fracture=False, fracture_between=None, ftype="unknown", location=None
        )
        _write_json(merged_dir / "fold_0_train.json", [bad_sample])
        errors, _warnings, _summary = run_quality_check(
            merged_dir=merged_dir,
            subvideos_meta_path=fake_project / "data" / "07_metadata" / "subvideos_meta.json",
            report_path=fake_project / "report.json",
            project_root=fake_project,
        )
        assert any(e["check"] == "type_closed_set" for e in errors)

    def test_fracture_between_bounds(self, fake_project: Path):
        merged_dir = fake_project / "data" / "06_merged"
        bad_sample = _make_sample(
            "bad", "video_0001", has_fracture=True, fracture_between=[6, 8], ftype="韧性断裂", location="inside_gauge"
        )
        _write_json(merged_dir / "fold_0_train.json", [bad_sample])
        errors, _warnings, _summary = run_quality_check(
            merged_dir=merged_dir,
            subvideos_meta_path=fake_project / "data" / "07_metadata" / "subvideos_meta.json",
            report_path=fake_project / "report.json",
            project_root=fake_project,
        )
        assert any(e["check"] == "fracture_between" for e in errors)

    def test_train_ratio_out_of_range(self, fake_project: Path):
        merged_dir = fake_project / "data" / "06_merged"
        # 3 pos, 1 neg => ratio 3:1 > 2:1
        samples = [
            _make_sample("p1", "video_0001", True, [6, 7], "韧性断裂", "inside_gauge"),
            _make_sample("p2", "video_0002", True, [6, 7], "脆性断裂", "inside_gauge"),
            _make_sample("p3", "video_0004", True, [6, 7], "齐根断裂", "inside_gauge"),
            _make_sample("n1", "video_0003", False, None, "未断裂", None),
        ]
        _write_json(merged_dir / "fold_0_train.json", samples)
        errors, _warnings, _summary = run_quality_check(
            merged_dir=merged_dir,
            subvideos_meta_path=fake_project / "data" / "07_metadata" / "subvideos_meta.json",
            report_path=fake_project / "report.json",
            project_root=fake_project,
        )
        assert any(e["check"] == "train_ratio" and e["detail"] == "ratio_out_of_range" for e in errors)

    def test_truth_leakage_in_test_inputs(self, fake_project: Path):
        merged_dir = fake_project / "data" / "06_merged"
        bad_input = {
            "id": "video_0003",
            "video_id": "video_0003",
            "video_path": "data/01_videos/video_0003.mp4",
            "type": "韧性断裂",
        }
        _write_json(merged_dir / "test_inputs.json", [bad_input])
        errors, _warnings, _summary = run_quality_check(
            merged_dir=merged_dir,
            subvideos_meta_path=fake_project / "data" / "07_metadata" / "subvideos_meta.json",
            report_path=fake_project / "report.json",
            project_root=fake_project,
        )
        assert any(e["check"] == "test_input_isolation" for e in errors)

    def test_cross_split_leakage(self, fake_project: Path):
        merged_dir = fake_project / "data" / "06_merged"
        # video_0001 in both train and val
        train = [_make_sample("v1", "video_0001", True, [6, 7], "韧性断裂", "inside_gauge")]
        val = [_make_sample("v1_val", "video_0001", True, [6, 7], "韧性断裂", "inside_gauge")]
        _write_json(merged_dir / "fold_0_train.json", train)
        _write_json(merged_dir / "fold_0_val.json", val)
        errors, _warnings, _summary = run_quality_check(
            merged_dir=merged_dir,
            subvideos_meta_path=fake_project / "data" / "07_metadata" / "subvideos_meta.json",
            report_path=fake_project / "report.json",
            project_root=fake_project,
        )
        assert any(e["check"] == "cross_split_leakage" for e in errors)

    def test_missing_media_file(self, fake_project: Path):
        merged_dir = fake_project / "data" / "06_merged"
        sample = _make_sample(video_path="data/01_videos/missing.mp4")
        _write_json(merged_dir / "fold_0_train.json", [sample])
        errors, _warnings, _summary = run_quality_check(
            merged_dir=merged_dir,
            subvideos_meta_path=fake_project / "data" / "07_metadata" / "subvideos_meta.json",
            report_path=fake_project / "report.json",
            project_root=fake_project,
        )
        assert any(e["check"] == "media_path" for e in errors)

    def test_mock_processor_fingerprint_is_an_error(self, fake_project: Path):
        merged_dir = fake_project / "data" / "06_merged"
        sample = _make_sample(fingerprint="mock:diagnostic")
        _write_json(merged_dir / "fold_0_train.json", [sample])
        errors, _warnings, _summary = run_quality_check(
            merged_dir=merged_dir,
            subvideos_meta_path=fake_project / "data" / "07_metadata" / "subvideos_meta.json",
            report_path=fake_project / "report.json",
            project_root=fake_project,
        )
        assert any(
            e["check"] == "processor_fingerprint"
            and e["detail"] == "mock_or_theoretical_fingerprints_forbidden"
            for e in errors
        )

    def test_exclusion_without_reason(self, fake_project: Path):
        merged_dir = fake_project / "data" / "06_merged"
        subvideos_meta = fake_project / "data" / "07_metadata" / "subvideos_meta.json"
        _write_json(subvideos_meta, {"subvideos": [], "exclusions": [{"source_video": "video_0001"}]})
        errors, _warnings, _summary = run_quality_check(
            merged_dir=merged_dir,
            subvideos_meta_path=subvideos_meta,
            report_path=fake_project / "report.json",
            project_root=fake_project,
        )
        assert any(e["check"] == "exclusion_reason" for e in errors)

    def test_cli_returns_zero_on_pass(self, fake_project: Path):
        merged_dir = fake_project / "data" / "06_merged"
        report_path = fake_project / "cli_report.json"
        rc = main(
            [
                "--merged-dir",
                str(merged_dir),
                "--subvideos-meta",
                str(fake_project / "data" / "07_metadata" / "subvideos_meta.json"),
                "--report",
                str(report_path),
                "--project-root",
                str(fake_project),
            ]
        )
        assert rc == 0
        assert report_path.exists()

    def test_cli_returns_nonzero_on_fail(self, fake_project: Path):
        merged_dir = fake_project / "data" / "06_merged"
        bad_input = {"id": "video_0003", "video_id": "video_0003", "video_path": "data/01_videos/video_0003.mp4", "type": "韧性断裂"}
        _write_json(merged_dir / "test_inputs.json", [bad_input])
        rc = main(
            [
                "--merged-dir",
                str(merged_dir),
                "--subvideos-meta",
                str(fake_project / "data" / "07_metadata" / "subvideos_meta.json"),
                "--report",
                str(fake_project / "fail_report.json"),
                "--project-root",
                str(fake_project),
            ]
        )
        assert rc == 1
