from __future__ import annotations

from agent.scoring_v4_1 import (
    evaluate_thresholds,
    normalize_ground_truth,
    score_predictions,
)


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
