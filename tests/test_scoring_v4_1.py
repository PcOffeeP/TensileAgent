from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.scoring_v4_1 import (
    evaluate_thresholds,
    load_annotation_rows,
    load_scoring_records,
    normalize_ground_truth,
    score_predictions,
)
from agent.v2_comparison_scoring import load_common_records
from scripts.score_strategy_ab import _load_annotations


def test_ground_truth_mapping_is_unique_for_root_and_outside_cases() -> None:
    combined = normalize_ground_truth(
        {
            "video_id": "v1",
            "source_type": "界面脱粘、齐根断裂",
            "location": "outside_gauge",
            "has_fracture": True,
        }
    )
    assert combined["fracture_mechanism"] == "界面脱粘"
    assert combined["fracture_site"] == "grip_root"

    root_only = normalize_ground_truth(
        {
            "video_id": "v2",
            "source_type": "齐根断裂",
            "location": "outside_gauge",
            "has_fracture": True,
        }
    )
    assert root_only["fracture_mechanism"] is None
    assert root_only["fracture_site"] == "grip_root"

    non_root = normalize_ground_truth(
        {
            "video_id": "v3",
            "source_type": "脆性断裂",
            "location": "outside_gauge",
            "has_fracture": True,
        }
    )
    assert non_root["fracture_site"] == "outside_gauge_non_root"


def test_synthetic_gold_scoring_denominators_and_special_cases() -> None:
    truth = [
        normalize_ground_truth(
            {
                "video_id": "fracture",
                "source_type": "韧性断裂",
                "location": "inside_gauge",
                "has_fracture": True,
                "fracture_time": 10.0,
                "duration": 20.0,
            }
        ),
        normalize_ground_truth(
            {
                "video_id": "negative",
                "source_type": "未断裂",
                "has_fracture": False,
            }
        ),
        normalize_ground_truth(
            {
                "video_id": "special",
                "source_type": "视频异常",
            }
        ),
    ]
    predictions = [
        {
            "status": "fracture",
            "has_fracture": True,
            "time_range": [9.8, 10.2],
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
        },
        {"status": "no_fracture", "has_fracture": False},
        {
            "status": "unrecognized",
            "has_fracture": None,
            "special_case": "视频异常",
        },
    ]
    report = score_predictions(list(zip(truth, predictions)))
    assert report["has_fracture_accuracy"] == 1.0
    assert report["time_hit_rate"] == 1.0
    assert report["mechanism_macro_f1"] == 1.0
    assert report["site_macro_f1"] == 1.0
    assert report["joint_success_rate"] == 1.0
    assert report["special_case_results"] == [
        {"special_case": "视频异常", "correct": True}
    ]
    gates = evaluate_thresholds(
        report,
        {
            "has_fracture_accuracy": 0.85,
            "joint_success_rate": 0.65,
        },
    )
    assert gates["passed"] is True


def test_normalize_ground_truth_rejects_missing_or_invalid_values() -> None:
    with pytest.raises(ValueError, match="missing ground-truth label"):
        normalize_ground_truth({"video_id": "synthetic"})

    with pytest.raises(ValueError, match="missing ground-truth label"):
        normalize_ground_truth({"video_id": "synthetic", "source_type": "   "})

    with pytest.raises(ValueError, match="invalid has_fracture"):
        normalize_ground_truth(
            {"video_id": "v1", "source_type": "脆性断裂", "has_fracture": "maybe"}
        )

    with pytest.raises(ValueError, match="invalid numeric value for fracture_time"):
        normalize_ground_truth(
            {
                "video_id": "v1",
                "source_type": "脆性断裂",
                "fracture_time": "not-a-number",
            }
        )

    with pytest.raises(ValueError, match="invalid numeric value for duration"):
        normalize_ground_truth(
            {
                "video_id": "v1",
                "source_type": "脆性断裂",
                "duration": "nan",
            }
        )

    with pytest.raises(ValueError, match="invalid numeric value for duration"):
        normalize_ground_truth(
            {
                "video_id": "v1",
                "source_type": "脆性断裂",
                "duration": True,
            }
        )


def test_load_annotation_rows_enforces_schema_and_set_invariants(
    tmp_path: Path,
) -> None:
    def write_csv(name: str, content: str) -> Path:
        path = tmp_path / name
        path.write_text(content, encoding="utf-8")
        return path

    with pytest.raises(ValueError, match="missing header"):
        load_annotation_rows(write_csv("empty.csv", ""))

    with pytest.raises(ValueError, match="no data rows"):
        load_annotation_rows(write_csv("header_only.csv", "video_id,source_type\n"))

    with pytest.raises(ValueError, match="blank column name"):
        load_annotation_rows(
            write_csv("blank_col.csv", "video_id,,source_type\nv1,x,脆性断裂\n")
        )

    with pytest.raises(ValueError, match="duplicate column names"):
        load_annotation_rows(
            write_csv(
                "dup_col.csv",
                "video_id,source_type,source_type\nv1,脆性断裂,脆性断裂\n",
            )
        )

    with pytest.raises(ValueError, match="missing required ID column"):
        load_annotation_rows(write_csv("no_id_col.csv", "name,source_type\nv1,脆性断裂\n"))

    with pytest.raises(ValueError, match="missing required ground-truth label column"):
        load_annotation_rows(write_csv("no_label_col.csv", "video_id,notes\nv1,ok\n"))

    with pytest.raises(ValueError, match="column count does not match header"):
        load_annotation_rows(
            write_csv("too_many_cols.csv", "video_id,source_type\nv1,脆性断裂,extra\n")
        )

    with pytest.raises(ValueError, match="column count does not match header"):
        load_annotation_rows(
            write_csv("too_few_cols.csv", "video_id,source_type\nv1\n")
        )

    with pytest.raises(ValueError, match="missing video_id"):
        load_annotation_rows(
            write_csv("empty_id.csv", "video_id,source_type\n,脆性断裂\n")
        )

    with pytest.raises(ValueError, match="duplicate annotation video_id"):
        load_annotation_rows(
            write_csv(
                "dup_id.csv",
                "video_id,source_type\nv1,脆性断裂\nv1,未断裂\n",
            )
        )

    valid_csv = write_csv(
        "valid_en.csv",
        "video_id,source_type,location,has_fracture,fracture_time,duration\n"
        "v1,脆性断裂,inside_gauge,true,5.5s,20.0\n"
        "v2,未断裂,,false,,20.0\n",
    )
    rows = load_annotation_rows(valid_csv)
    assert set(rows) == {"v1", "v2"}
    assert normalize_ground_truth(rows["v1"])["fracture_time"] == 5.5

    subset = load_annotation_rows(valid_csv, allowed_video_ids={"v1"})
    assert set(subset) == {"v1"}

    with pytest.raises(ValueError, match="annotation/input identity mismatch"):
        load_annotation_rows(valid_csv, allowed_video_ids={"v1", "v3"})


def test_chinese_annotation_csv_and_shared_loaders_fail_closed(tmp_path: Path) -> None:
    zh_csv = tmp_path / "zh_annotations.csv"
    zh_csv.write_text(
        "id,断裂模式,断裂位置,断裂时间点,视频时长\n"
        "video_0001,韧性断裂,inside_gauge,12.5s,20\n"
        "video_0002,未断裂,,,20\n",
        encoding="utf-8-sig",
    )
    loaded = _load_annotations(zh_csv)
    assert set(loaded) == {"video_0001", "video_0002"}
    gt_pos = normalize_ground_truth(loaded["video_0001"])
    assert gt_pos["has_fracture"] is True
    assert gt_pos["fracture_mechanism"] == "韧性断裂"
    assert gt_pos["fracture_site"] == "inside_gauge"
    assert gt_pos["fracture_time"] == 12.5
    assert gt_pos["duration"] == 20.0

    results_root = tmp_path / "results"
    for vid, status, has_f in (
        ("video_0001", "fracture", True),
        ("video_0002", "no_fracture", False),
    ):
        (results_root / vid).mkdir(parents=True)
        (results_root / vid / "result.json").write_text(
            json.dumps(
                {
                    "runner_result": {
                        "result": {
                            "schema_version": "tensile-agent/result/v4.1",
                            "video_id": vid,
                            "status": status,
                            "has_fracture": has_f,
                        }
                    }
                }
            ),
            encoding="utf-8",
        )

    v4_records = load_scoring_records(
        zh_csv,
        results_root,
        allowed_video_ids={"video_0001", "video_0002"},
    )
    assert len(v4_records) == 2

    common_records = load_common_records(
        zh_csv,
        results_root,
        schema_version="tensile-agent/result/v4.1",
        allowed_video_ids={"video_0001", "video_0002"},
    )
    assert len(common_records) == 2

    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("id,断裂模式\nvideo_0001,韧性断裂,extra\n", encoding="utf-8")
    with pytest.raises(ValueError, match="column count does not match header"):
        _load_annotations(bad_csv)
    with pytest.raises(ValueError, match="column count does not match header"):
        load_scoring_records(bad_csv, results_root, allowed_video_ids={"video_0001"})
    with pytest.raises(ValueError, match="column count does not match header"):
        load_common_records(
            bad_csv,
            results_root,
            schema_version="tensile-agent/result/v4.1",
            allowed_video_ids={"video_0001"},
        )
