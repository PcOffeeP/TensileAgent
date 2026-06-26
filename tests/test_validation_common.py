from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
VALIDATION_DIR = ROOT / "finetune" / "validation"
sys.path.insert(0, str(VALIDATION_DIR))
sys.path.insert(0, str(ROOT))

from common import (
    _confidence_bucket,
    _extract_confidence,
    _update_confidence_bucket,
    compute_type_metrics,
    finalize_time_aggregator,
    init_time_aggregator,
    parse_time_range,
    time_range_contains_gt,
    update_time_aggregator,
    write_json,
    write_jsonl,
)
from config import FRACTURE_CLASSES


def test_parse_time_range_valid():
    assert parse_time_range([1.0, 2.0]) == (1.0, 2.0)
    assert parse_time_range((1.0, 2.0)) == (1.0, 2.0)
    assert parse_time_range('[1.0, 2.0]') == (1.0, 2.0)
    assert parse_time_range('[2.0, 1.0]') == (1.0, 2.0)
    assert parse_time_range('  [1.0, 2.0]  ') == (1.0, 2.0)


def test_parse_time_range_invalid():
    assert parse_time_range(None) is None
    assert parse_time_range('') is None
    assert parse_time_range('not-a-range') is None
    assert parse_time_range([1.0]) is None
    assert parse_time_range([1.0, 2.0, 3.0]) is None
    assert parse_time_range(['a', 'b']) is None


def test_time_range_contains_gt_hit():
    assert time_range_contains_gt((1.0, 3.0), 2.0) is True
    assert time_range_contains_gt((1.0, 3.0), 1.0) is True
    assert time_range_contains_gt((1.0, 3.0), 3.0) is True


def test_time_range_contains_gt_miss():
    assert time_range_contains_gt((1.0, 3.0), 0.5) is False
    assert time_range_contains_gt((1.0, 3.0), 4.0) is False
    assert time_range_contains_gt(None, 2.0) is False
    assert time_range_contains_gt((1.0, 3.0), None) is False


def _make_record(pred_time: float, gt_time: float, time_available: bool = True, **extras) -> dict:
    return {
        "video_id": "v001",
        "gt_time_sec": gt_time,
        "pred_time_sec": pred_time,
        "time_available": time_available,
        "gt_type": "韧性断裂",
        "pred_type_norm": None,
        "json_valid": True,
        "failure_reason": None,
        **extras,
    }


def test_time_aggregator_within_thresholds():
    agg = init_time_aggregator()
    records = [
        _make_record(10.0, 10.5),  # error 0.5 -> within 1/3/5
        _make_record(20.0, 21.5),  # error 1.5 -> within 3/5
        _make_record(30.0, 33.5),  # error 3.5 -> within 5
        _make_record(40.0, 46.5),  # error 6.5 -> none
    ]
    for record in records:
        update_time_aggregator(agg, record)

    assert agg["count"] == 4
    assert agg["applicable_count"] == 4
    assert agg["parseable_prediction_count"] == 4
    assert agg["within_1s_count"] == 1
    assert agg["within_3s_count"] == 2
    assert agg["within_5s_count"] == 3

    metrics = finalize_time_aggregator(agg)
    assert metrics["within_1s"] == round(1 / 4, 6)
    assert metrics["within_3s"] == round(2 / 4, 6)
    assert metrics["within_5s"] == round(3 / 4, 6)


def test_time_aggregator_excludes_no_gt_time():
    agg = init_time_aggregator()
    update_time_aggregator(agg, _make_record(10.0, 10.5, time_available=False))
    update_time_aggregator(agg, _make_record(20.0, 20.5))

    assert agg["count"] == 2
    assert agg["applicable_count"] == 1
    assert agg["excluded_no_gt_time"] == 1

    metrics = finalize_time_aggregator(agg)
    assert metrics["within_1s"] == 1.0


def test_confidence_buckets_numeric_scores():
    agg = init_time_aggregator()
    records = [
        _make_record(10.0, 10.2, pred_time_range=[9.5, 10.5], pred_confidence_score=0.85, pred_confidence_level="高"),
        _make_record(20.0, 20.8, pred_time_range=[19.5, 20.5], pred_confidence_score=0.85, pred_confidence_level="高"),
        _make_record(30.0, 30.1, pred_time_range=[29.5, 30.5], pred_confidence_score=0.25, pred_confidence_level="低"),
    ]
    for record in records:
        update_time_aggregator(agg, record)

    metrics = finalize_time_aggregator(agg)
    buckets = {row["bucket"]: row for row in metrics["confidence_buckets"]}

    assert "0.8-0.9" in buckets
    assert "0.2-0.3" in buckets
    assert buckets["0.8-0.9"]["count"] == 2
    assert buckets["0.2-0.3"]["count"] == 1
    assert buckets["0.8-0.9"]["range_hit_rate"] == 0.5
    assert buckets["0.8-0.9"]["within_1s_rate"] == 1.0


def test_confidence_buckets_from_level_only():
    agg = init_time_aggregator()
    records = [
        _make_record(10.0, 10.1, pred_confidence_level="中"),
    ]
    for record in records:
        update_time_aggregator(agg, record)

    metrics = finalize_time_aggregator(agg)
    buckets = {row["bucket"]: row for row in metrics["confidence_buckets"]}
    # Level "中" is normalized to score 0.6 and binned numerically.
    assert "0.6-0.7" in buckets
    assert buckets["0.6-0.7"]["count"] == 1
    assert buckets["0.6-0.7"]["avg_confidence"] == 0.6


def test_extract_confidence_rejects_nan_and_inf():
    assert _extract_confidence({"pred_confidence_score": float("nan")}) == (None, None)
    assert _extract_confidence({"pred_confidence_score": "nan"}) == (None, None)
    assert _extract_confidence({"pred_confidence_score": float("inf")}) == (None, None)
    assert _extract_confidence({"pred_confidence_score": float("-inf")}) == (None, None)
    assert _extract_confidence({"confidence_score": "not-a-number"}) == (None, None)
    assert _extract_confidence({"pred_confidence_score": 0.85}) == (0.85, None)


def test_parse_time_range_rejects_nan_and_inf():
    assert parse_time_range([float("nan"), 1.0]) is None
    assert parse_time_range([1.0, float("inf")]) is None
    assert parse_time_range([float("-inf"), 1.0]) is None
    assert parse_time_range((float("nan"), float("nan"))) is None
    assert parse_time_range('["NaN", 1.0]') is None
    assert parse_time_range('[1.0, "Infinity"]') is None


def test_extract_confidence_clamps_out_of_range():
    assert _extract_confidence({"pred_confidence_score": 1.5}) == (1.0, None)
    assert _extract_confidence({"pred_confidence_score": -0.3}) == (0.0, None)
    assert _extract_confidence({"pred_confidence_score": 0.0}) == (0.0, None)
    assert _extract_confidence({"pred_confidence_score": 1.0}) == (1.0, None)
    assert _extract_confidence({"confidence_score": 2.0}) == (1.0, None)


def test_confidence_bucket_rejects_nan_and_inf():
    assert _confidence_bucket(float("nan")) is None
    assert _confidence_bucket(float("inf")) is None
    assert _confidence_bucket(float("-inf")) is None
    assert _confidence_bucket(0.85) == "0.8-0.9"


def test_update_confidence_bucket_skips_invalid_confidence():
    buckets: dict[str, Any] = {}
    base_record = {"pred_time_sec": 10.0}

    _update_confidence_bucket(
        buckets, {**base_record, "pred_confidence_score": float("nan")}, None, 10.0
    )
    _update_confidence_bucket(
        buckets, {**base_record, "pred_confidence_score": float("inf")}, None, 10.0
    )
    _update_confidence_bucket(
        buckets, {**base_record, "pred_confidence_score": "invalid"}, None, 10.0
    )
    _update_confidence_bucket(
        buckets, {**base_record, "pred_confidence_level": "unknown"}, None, 10.0
    )
    assert buckets == {}

    _update_confidence_bucket(
        buckets, {**base_record, "pred_confidence_score": 0.85}, None, 10.0
    )
    assert "0.8-0.9" in buckets
    assert buckets["0.8-0.9"]["count"] == 1


def test_time_aggregator_ignores_invalid_confidence_for_buckets():
    agg = init_time_aggregator()
    records = [
        # Invalid confidence values must not be assigned to any bucket,
        # but the records themselves are still parseable for time metrics.
        _make_record(10.0, 10.2, pred_confidence_score=float("nan")),
        _make_record(20.0, 20.2, pred_confidence_score=float("inf")),
        _make_record(30.0, 30.2, pred_confidence_score="not-a-number"),
        _make_record(40.0, 40.2, pred_confidence_level="unknown"),
        # Valid confidence should land in a bucket.
        _make_record(50.0, 50.2, pred_confidence_score=0.85),
    ]
    for record in records:
        update_time_aggregator(agg, record)

    metrics = finalize_time_aggregator(agg)
    buckets = {row["bucket"]: row for row in metrics["confidence_buckets"]}

    assert set(buckets.keys()) == {"0.8-0.9"}
    assert buckets["0.8-0.9"]["count"] == 1
    assert buckets["0.8-0.9"]["avg_confidence"] == 0.85
    # Time metrics should still account for all parseable predictions.
    assert metrics["parseable_prediction_count"] == 5
    assert metrics["within_1s"] == 1.0

    # The final payload must be JSON-serializable (no NaN literal).
    dumped = json.dumps(metrics)
    assert "NaN" not in dumped
    assert "Infinity" not in dumped
    assert "-Infinity" not in dumped


def test_common_write_json_rejects_nan(tmp_path: Path):
    with pytest.raises(ValueError):
        write_json(tmp_path / "bad.json", {"value": float("nan")})


def test_write_jsonl_rejects_nan(tmp_path: Path):
    with pytest.raises(ValueError):
        write_jsonl(tmp_path / "bad.jsonl", [{"value": float("nan")}])


def test_type_metrics_only_on_fracture_classes():
    """Non-fracture / abnormal samples must not affect the 7-class macro-F1."""
    fracture_records = [
        {"gt_type": "韧性断裂", "pred_type_norm": "韧性断裂", "has_fracture": True},
        {"gt_type": "脆性断裂", "pred_type_norm": "韧性断裂", "has_fracture": True},
    ]
    summary, per_class, _ = compute_type_metrics(fracture_records)
    base_macro_f1 = summary["macro_f1"]
    assert summary["count"] == 2

    mixed_records = fracture_records + [
        {"gt_type": "未断裂", "pred_type_norm": "韧性断裂", "has_fracture": False},
        {"gt_type": "视频异常", "pred_type_norm": "脆性断裂", "has_fracture": False},
        {"gt_type": "未夹紧", "pred_type_norm": "界面脱粘", "has_fracture": False},
    ]
    summary2, per_class2, _ = compute_type_metrics(mixed_records)

    assert summary2["macro_f1"] == base_macro_f1
    assert summary2["count"] == 2
    assert summary2["total_count"] == 5
    assert {row["label"] for row in per_class2} == {row["label"] for row in per_class}
    assert all(row["label"] in FRACTURE_CLASSES for row in per_class2)


def test_type_metrics_tracks_failure_rate_for_non_fracture():
    """Non-fracture / abnormal samples are tracked via failure rate, not macro-F1."""
    records = [
        {"gt_type": "未断裂", "pred_type_norm": "未断裂", "has_fracture": False},
        {"gt_type": "未夹紧", "pred_type_norm": "韧性断裂", "has_fracture": False},
        {"gt_type": "视频异常", "pred_type_norm": "视频异常", "has_fracture": False},
    ]
    summary, per_class, confusion = compute_type_metrics(records)

    assert summary["count"] == 0
    assert summary["macro_f1"] == 0.0
    assert summary["type_non_fracture_count"] == 3
    assert summary["type_failure_count"] == 1
    assert summary["type_failure_rate"] == round(1 / 3, 6)

    assert all(row["label"] in FRACTURE_CLASSES for row in per_class)
    assert all(row["gt_type"] in FRACTURE_CLASSES for row in confusion)


def test_extract_confidence_maps_untrusted_level():
    """The four-level confidence mapping includes '不可信'."""
    assert _extract_confidence({"pred_confidence_level": "不可信"}) == (0.25, "不可信")
    assert _extract_confidence({"confidence_level": "不可信"}) == (0.25, "不可信")


def test_confidence_buckets_untrusted_level():
    """Level-only '不可信' records are binned using the canonical score."""
    agg = init_time_aggregator()
    update_time_aggregator(agg, _make_record(10.0, 10.1, pred_confidence_level="不可信"))

    metrics = finalize_time_aggregator(agg)
    buckets = {row["bucket"]: row for row in metrics["confidence_buckets"]}
    assert "0.2-0.3" in buckets
    assert buckets["0.2-0.3"]["count"] == 1
    assert buckets["0.2-0.3"]["avg_confidence"] == 0.25


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
