from __future__ import annotations

import json

import pytest

from agent.scoring_v4_1 import normalize_ground_truth
from agent.strategy_ab import (
    DIAGNOSTIC_30_IDS,
    coverage_ranges,
    fixed_scan_ranges,
    map_single_call,
    reduce_fixed_scan,
)
from agent.strategy_ab_protocol import (
    build_protocol_manifest,
    derive_protocol_sets,
    verify_manifest_inputs,
)
from agent.strategy_ab_scoring import paired_bootstrap_delta, presence_correct, score_method


def _round(
    sample_range: list[float],
    state: str,
    *,
    mechanism: str | None = None,
    site: str | None = None,
    special: str | None = None,
    ok: bool = True,
) -> dict:
    return {
        "ok": ok,
        "sample_range": sample_range,
        "model_output": {
            "clip_state": state,
            "fracture_mechanism": mechanism,
            "fracture_site": site,
            "special_case": special,
        },
        "validation_error": None if ok else {"code": "bad"},
    }


def test_fixed_scan_schedule_is_frozen_and_covers_by_call_six() -> None:
    ranges = fixed_scan_ranges(32.0)
    assert len(ranges) == 10
    assert ranges[0] == [0.0, 32.0]
    assert ranges[1:6] == coverage_ranges(32.0)
    assert ranges[1:6] == [
        [0.0, 8.0],
        [6.0, 14.0],
        [12.0, 20.0],
        [18.0, 26.0],
        [24.0, 32.0],
    ]


def test_single_call_mapping_is_raw_and_special_case_abstains() -> None:
    positive = map_single_call(
        _round([0.0, 10.0], "发生断裂", mechanism="韧性断裂")
    )
    assert positive["status"] == "fracture"
    assert positive["fracture_type"] == "韧性断裂"
    special = map_single_call(
        _round([0.0, 10.0], "未断裂", special="视频异常")
    )
    assert special["status"] == "unrecognized"
    assert special["special_case"] == "视频异常"


def test_fixed_scan_no_fracture_requires_all_five_coverage_windows() -> None:
    ranges = fixed_scan_ranges(32.0)
    first_five = [_round(ranges[0], "未断裂")] + [
        _round(item, "未断裂") for item in ranges[1:5]
    ]
    assert reduce_fixed_scan(first_five, duration=32.0)["status"] == "unrecognized"
    complete = first_five + [_round(ranges[5], "未断裂")]
    result = reduce_fixed_scan(complete, duration=32.0)
    assert result["status"] == "no_fracture"
    assert result["request_count"] == 6


def test_fixed_scan_requires_two_positives_and_publishes_only_narrow_bounds() -> None:
    rounds = [
        _round([0.0, 40.0], "发生断裂", mechanism="韧性断裂", site="inside_gauge"),
        _round([20.0, 40.0], "发生断裂", mechanism="韧性断裂", site="inside_gauge"),
        _round([20.0, 29.0], "未断裂"),
        _round([30.0, 40.0], "已断裂", mechanism="韧性断裂", site="inside_gauge"),
    ]
    result = reduce_fixed_scan(rounds, duration=40.0)
    assert result["status"] == "fracture"
    assert result["time_range"] == [29.0, 30.0]
    assert result["fracture_type"] == "韧性断裂"
    assert result["location"] == "inside_gauge"


def test_fixed_scan_conflict_keeps_fracture_but_withholds_time() -> None:
    rounds = [
        _round([0.0, 40.0], "发生断裂"),
        _round([10.0, 20.0], "发生断裂"),
        _round([0.0, 30.0], "未断裂"),
    ]
    result = reduce_fixed_scan(rounds, duration=40.0)
    assert result["status"] == "fracture"
    assert result["time_range"] is None
    assert result["event_bounds_conflicted"] is True


def test_coverage_negatives_do_not_become_event_boundaries_after_late_positive() -> None:
    ranges = fixed_scan_ranges(32.0)
    rounds = [
        _round(ranges[0], "未断裂"),
        _round(ranges[1], "未断裂"),
        _round(ranges[2], "发生断裂"),
        _round(ranges[3], "发生断裂"),
    ]
    result = reduce_fixed_scan(rounds, duration=32.0)
    assert result["status"] == "fracture"
    assert result["event_bounds"] == [12.0, 14.0]
    assert result["time_range"] is None


def test_invalid_round_consumes_budget_but_not_evidence() -> None:
    result = reduce_fixed_scan(
        [_round([0.0, 10.0], "无法判断", ok=False)],
        duration=10.0,
    )
    assert result["request_count"] == 1
    assert result["valid_response_count"] == 0


def test_protocol_sets_and_hash_verification(tmp_path) -> None:
    all_ids = {f"video_{index:04d}" for index in range(1, 111)}
    test = {
        "video_0005",
        "video_0008",
        "video_0010",
        "video_0025",
        "video_0018",
        "video_0019",
        "video_0032",
        "video_0037",
        "video_0038",
        "video_0041",
        "video_0062",
        "video_0063",
        "video_0067",
        "video_0078",
        "video_0082",
        "video_0087",
        "video_0088",
        "video_0089",
        "video_0093",
        "video_0094",
        "video_0095",
    }
    remaining = sorted(all_ids - test)
    val, train = set(remaining[:30]), set(remaining[30:])
    sets = derive_protocol_sets(tuple(train), tuple(val), tuple(test))
    assert len(sets["diagnostic30"]) == len(DIAGNOSTIC_30_IDS) == 30
    assert len(sets["locked80"]) == 80
    assert len(sets["confirmatory_test17"]) == 17

    splits = tmp_path / "splits"
    splits.mkdir()
    for name, ids in (
        ("fold_0_train.json", train),
        ("fold_0_val.json", val),
        ("test.json", test),
    ):
        (splits / name).write_text(
            json.dumps({"video_ids": sorted(ids), "count": len(ids)}),
            encoding="utf-8",
        )
    annotations = tmp_path / "annotations.csv"
    annotations.write_text("id,断裂模式\nvideo_0001,韧性断裂\n", encoding="utf-8")
    config = tmp_path / "config.yaml"
    config.write_text("agent: {}\n", encoding="utf-8")
    videos = tmp_path / "videos"
    videos.mkdir()
    for video_id in sorted(all_ids):
        (videos / f"{video_id}.mp4").write_bytes(video_id.encode())
    manifest = build_protocol_manifest(
        splits_dir=splits,
        annotations_csv=annotations,
        config_path=config,
        videos_root=videos,
    )
    verify_manifest_inputs(manifest)
    config.write_text("agent: {max_rounds: 9}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        verify_manifest_inputs(manifest)


def test_chinese_annotation_normalization_and_strategy_metrics() -> None:
    truth = normalize_ground_truth(
        {
            "id": "video_0001",
            "断裂模式": "韧性断裂",
            "断裂位置": "inside_gauge",
            "断裂时间点": "10.25s",
            "视频时长": "12.0",
            "has_fracture": "TRUE",
        }
    )
    assert truth["fracture_time"] == 10.25
    assert truth["fracture_mechanism"] == "韧性断裂"
    prediction = {
        "has_fracture": True,
        "time_range": [10.0, 10.5],
        "fracture_type": "韧性断裂",
        "location": "inside_gauge",
        "special_case": None,
    }
    report = score_method([(truth, prediction, 4)])
    assert report["presence"]["f1"] == 1.0
    assert report["time"]["strict_hit_rate_all_positives"] == 1.0
    assert report["efficiency"]["mean_requests"] == 4.0


def test_paired_bootstrap_reports_b_minus_c_direction() -> None:
    truths = [
        {"has_fracture": True, "special_case": None},
        {"has_fracture": False, "special_case": None},
    ]
    records_b = [
        (truths[0], {"has_fracture": True}, 2),
        (truths[1], {"has_fracture": False}, 2),
    ]
    records_c = [
        (truths[0], {"has_fracture": False}, 2),
        (truths[1], {"has_fracture": False}, 2),
    ]
    report = paired_bootstrap_delta(
        records_b,
        records_c,
        score=presence_correct,
        iterations=200,
    )
    assert report["delta_b_minus_c"] == 0.5
