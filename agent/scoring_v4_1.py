"""Frozen V4.1 scoring semantics, exercised on synthetic fixtures before Stage G."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


FRACTURE_MECHANISMS = {
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "爆炸性断裂",
    "半脆半韧断裂",
}
SPECIAL_CASES = {"未夹紧", "视频异常"}


def normalize_ground_truth(row: dict[str, Any]) -> dict[str, Any]:
    """Map one source annotation into the unique V4.1 Agent taxonomy."""
    source_type = str(
        row.get("source_type")
        or row.get("type")
        or row.get("fracture_type")
        or ""
    ).strip()
    source_location = row.get("location_canonical", row.get("location"))
    special_case = source_type if source_type in SPECIAL_CASES else None
    if "界面脱粘" in source_type:
        mechanism = "界面脱粘"
    elif source_type == "齐根断裂":
        mechanism = None
    elif source_type in FRACTURE_MECHANISMS:
        mechanism = source_type
    else:
        mechanism = None

    if "齐根断裂" in source_type:
        site = "grip_root"
    elif source_location == "inside_gauge":
        site = "inside_gauge"
    elif source_location == "outside_gauge":
        site = "outside_gauge_non_root"
    else:
        site = None

    raw_has_fracture = row.get("has_fracture")
    if isinstance(raw_has_fracture, str):
        lowered = raw_has_fracture.strip().lower()
        if lowered in {"true", "1", "yes"}:
            raw_has_fracture = True
        elif lowered in {"false", "0", "no"}:
            raw_has_fracture = False
    if isinstance(raw_has_fracture, bool):
        has_fracture = raw_has_fracture
    else:
        has_fracture = source_type not in {"未断裂", *SPECIAL_CASES}
    if special_case is not None:
        has_fracture = None
        site = None
        mechanism = None
    return {
        "video_id": row.get("video_id"),
        "has_fracture": has_fracture,
        "fracture_mechanism": mechanism,
        "fracture_site": site,
        "special_case": special_case,
        "fracture_time": _optional_number(
            row.get("fracture_time", row.get("break_time"))
        ),
        "duration": _optional_number(
            row.get("duration", row.get("duration_seconds"))
        ),
    }


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _macro_f1(pairs: Iterable[tuple[Any, Any]], labels: set[Any]) -> float | None:
    scores: list[float] = []
    materialized = list(pairs)
    for label in sorted(labels):
        tp = sum(gt == label and pred == label for gt, pred in materialized)
        fp = sum(gt != label and pred == label for gt, pred in materialized)
        fn = sum(gt == label and pred != label for gt, pred in materialized)
        if tp + fn == 0:
            continue
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn)
        scores.append(
            2 * precision * recall / (precision + recall)
            if precision + recall
            else 0.0
        )
    return sum(scores) / len(scores) if scores else None


def _time_hit(gt: dict[str, Any], pred: dict[str, Any]) -> bool | None:
    timestamp = gt.get("fracture_time")
    duration = gt.get("duration")
    interval = pred.get("time_range")
    if not isinstance(timestamp, (int, float)) or not isinstance(duration, (int, float)):
        return None
    if not isinstance(interval, list) or len(interval) != 2:
        return False
    tolerance = max(1.0, float(duration) * 0.05)
    return float(interval[0]) - tolerance <= float(timestamp) <= float(interval[1]) + tolerance


def score_predictions(
    records: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    """Score normalized truth and public Agent predictions with fixed denominators."""
    normal = [(gt, pred) for gt, pred in records if gt["special_case"] is None]
    positives = [(gt, pred) for gt, pred in normal if gt["has_fracture"] is True]
    negatives = [(gt, pred) for gt, pred in normal if gt["has_fracture"] is False]
    presence_hits = [
        pred.get("has_fracture") == gt["has_fracture"] for gt, pred in normal
    ]
    time_hits = [
        hit
        for gt, pred in positives
        if (hit := _time_hit(gt, pred)) is not None
    ]
    mechanism_pairs = [
        (gt["fracture_mechanism"], pred.get("fracture_type"))
        for gt, pred in positives
        if gt["fracture_mechanism"] is not None
    ]
    site_pairs = [
        (gt["fracture_site"], pred.get("location"))
        for gt, pred in positives
        if gt["fracture_site"] is not None
    ]
    joint: list[bool] = []
    for gt, pred in normal:
        ok = pred.get("has_fracture") == gt["has_fracture"]
        if gt["has_fracture"] is True:
            time_hit = _time_hit(gt, pred)
            ok = (
                ok
                and (time_hit is not False)
                and (
                    gt["fracture_mechanism"] is None
                    or pred.get("fracture_type") == gt["fracture_mechanism"]
                )
                and (
                    gt["fracture_site"] is None
                    or pred.get("location") == gt["fracture_site"]
                )
            )
        joint.append(ok)
    special = [
        (
            gt["special_case"],
            pred.get("status") == "unrecognized"
            and pred.get("special_case") == gt["special_case"],
        )
        for gt, pred in records
        if gt["special_case"] is not None
    ]
    return {
        "has_fracture_accuracy": sum(presence_hits) / len(presence_hits) if presence_hits else None,
        "fracture_recall": (
            sum(pred.get("has_fracture") is True for _, pred in positives) / len(positives)
            if positives
            else None
        ),
        "no_fracture_recall": (
            sum(pred.get("has_fracture") is False for _, pred in negatives) / len(negatives)
            if negatives
            else None
        ),
        "time_hit_rate": sum(time_hits) / len(time_hits) if time_hits else None,
        "mechanism_macro_f1": _macro_f1(mechanism_pairs, FRACTURE_MECHANISMS),
        "site_macro_f1": _macro_f1(
            site_pairs,
            {"inside_gauge", "outside_gauge_non_root", "grip_root"},
        ),
        "joint_success_rate": sum(joint) / len(joint) if joint else None,
        "special_case_results": [
            {"special_case": name, "correct": correct} for name, correct in special
        ],
        "special_case_counts": dict(Counter(name for name, _ in special)),
        "denominators": {
            "presence": len(normal),
            "fracture": len(positives),
            "no_fracture": len(negatives),
            "time": len(time_hits),
            "mechanism": len(mechanism_pairs),
            "site": len(site_pairs),
            "joint": len(joint),
            "special_case": len(special),
        },
    }


def load_scoring_records(
    annotations_csv: str | Path,
    results_root: str | Path,
    *,
    allowed_video_ids: set[str] | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Join source CSV rows to immutable batch results by exact video_id."""
    annotations: dict[str, dict[str, Any]] = {}
    with Path(annotations_csv).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            video_id = str(
                row.get("video_id")
                or row.get("video")
                or row.get("id")
                or ""
            ).strip()
            if not video_id:
                raise ValueError("annotation row is missing video_id")
            if allowed_video_ids is not None and video_id not in allowed_video_ids:
                continue
            if video_id in annotations:
                raise ValueError(f"duplicate annotation video_id: {video_id}")
            row["video_id"] = video_id
            annotations[video_id] = row

    records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    root = Path(results_root)
    for video_id, row in sorted(annotations.items()):
        result_path = root / video_id / "result.json"
        if not result_path.is_file():
            raise ValueError(f"missing immutable result: {video_id}")
        batch_record = json.loads(result_path.read_text(encoding="utf-8"))
        prediction = batch_record.get("runner_result", {}).get("result")
        if not isinstance(prediction, dict):
            raise ValueError(f"invalid runner result: {video_id}")
        if prediction.get("video_id") != video_id:
            raise ValueError(f"result identity mismatch: {video_id}")
        records.append((normalize_ground_truth(row), prediction))
    return records


def evaluate_thresholds(
    report: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate numeric gates without hiding missing metrics."""
    gates: dict[str, dict[str, Any]] = {}
    for metric, minimum in thresholds.items():
        if not isinstance(minimum, (int, float)):
            continue
        value = report.get(metric)
        gates[metric] = {
            "value": value,
            "minimum": float(minimum),
            "passed": isinstance(value, (int, float)) and value >= float(minimum),
        }
    return {
        "passed": bool(gates) and all(item["passed"] for item in gates.values()),
        "gates": gates,
    }
