from agent.v2_comparison_scoring import (
    adapt_prediction,
    compare_common_reports,
    compare_special_cases,
    score_common,
)


def test_v2_combined_root_type_maps_to_common_taxonomy() -> None:
    prediction = adapt_prediction(
        {
            "schema_version": "tensile-agent/result/v2",
            "video_id": "v",
            "status": "fracture",
            "has_fracture": True,
            "time_range": [1.0, 2.0],
            "fracture_type": "界面脱粘、齐根断裂",
            "location": "outside_gauge",
        },
        "tensile-agent/result/v2",
    )
    assert prediction["fracture_mechanism"] == "界面脱粘"
    assert prediction["coarse_site"] == "outside_gauge"


def test_v2_unrecognized_reason_maps_special_case() -> None:
    prediction = adapt_prediction(
        {
            "schema_version": "tensile-agent/result/v2",
            "video_id": "v",
            "status": "unrecognized",
            "has_fracture": None,
            "unrecognized_reason": "not_clamped",
        },
        "tensile-agent/result/v2",
    )
    assert prediction["special_case"] == "未夹紧"


def test_common_scoring_uses_coarse_site_and_special_case() -> None:
    records = [
        (
            {
                "has_fracture": True,
                "fracture_mechanism": "脆性断裂",
                "fracture_site": "grip_root",
                "special_case": None,
                "fracture_time": 2.0,
                "duration": 10.0,
            },
            {
                "status": "fracture",
                "has_fracture": True,
                "time_range": [1.5, 2.5],
                "fracture_mechanism": "脆性断裂",
                "coarse_site": "outside_gauge",
                "special_case": None,
            },
        ),
        (
            {
                "has_fracture": None,
                "fracture_mechanism": None,
                "fracture_site": None,
                "special_case": "未夹紧",
                "fracture_time": None,
                "duration": 10.0,
            },
            {
                "status": "unrecognized",
                "has_fracture": None,
                "time_range": None,
                "fracture_mechanism": None,
                "coarse_site": None,
                "special_case": "未夹紧",
            },
        ),
    ]
    report = score_common(records)
    assert report["joint_common_success_rate"] == 1.0
    assert report["coarse_site_macro_f1"] == 1.0
    assert report["special_case_results"][0]["correct"] is True


def test_non_regression_uses_prefrozen_absolute_tolerance() -> None:
    v2 = {metric: 0.8 for metric in (
        "has_fracture_accuracy",
        "fracture_recall",
        "no_fracture_recall",
        "time_hit_rate",
        "mechanism_macro_f1",
        "coarse_site_macro_f1",
        "joint_common_success_rate",
    )}
    v4 = {metric: 0.77 for metric in v2}
    report = compare_common_reports(v4, v2, absolute_tolerance=0.03)
    assert report["passed"] is True
    v4["time_hit_rate"] = 0.76
    assert (
        compare_common_reports(v4, v2, absolute_tolerance=0.03)["passed"]
        is False
    )


def test_special_case_comparison_requires_exact_v4_result() -> None:
    exact = {
        "special_case_results": [
            {"special_case": "未夹紧", "correct": True},
            {"special_case": "视频异常", "correct": True},
        ]
    }
    v2 = {
        "special_case_results": [
            {"special_case": "未夹紧", "correct": True},
            {"special_case": "视频异常", "correct": False},
        ]
    }
    assert compare_special_cases(exact, v2)["passed"] is True
    exact["special_case_results"][1]["correct"] = False
    assert compare_special_cases(exact, v2)["passed"] is False
