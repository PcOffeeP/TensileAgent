"""Frozen V4.1 scoring semantics, exercised on synthetic fixtures before Stage G."""

from __future__ import annotations

import csv
import json
import math
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
ANNOTATION_ID_COLUMNS = ("video_id", "video", "id")
ANNOTATION_LABEL_COLUMNS = (
    "has_fracture",
    "source_type",
    "type",
    "fracture_type",
    "断裂模式",
)


def normalize_ground_truth(row: dict[str, Any]) -> dict[str, Any]:
    """Map one source annotation into the unique V4.1 Agent taxonomy."""
    source_type = str(
        row.get("source_type")
        or row.get("type")
        or row.get("fracture_type")
        or row.get("断裂模式")
        or ""
    ).strip()
    source_location = row.get(
        "location_canonical",
        row.get("location", row.get("断裂位置")),
    )
    special_case = source_type if source_type in SPECIAL_CASES else None
    if "界面脱粘" in source_type:
        mechanism = "界面脱粘"
    elif source_type == "齐根断裂":
        mechanism = None
    else:
        mechanism = next(
            (
                value
                for value in sorted(FRACTURE_MECHANISMS, key=len, reverse=True)
                if value in source_type
            ),
            None,
        )

    if "齐根断裂" in source_type:
        site = "grip_root"
    elif source_location == "inside_gauge":
        site = "inside_gauge"
    elif source_location == "outside_gauge":
        site = "outside_gauge_non_root"
    else:
        site = None

    raw_has_fracture = row.get("has_fracture")
    parsed_has_fracture: bool | None
    if raw_has_fracture is None:
        parsed_has_fracture = None
    elif isinstance(raw_has_fracture, bool):
        parsed_has_fracture = raw_has_fracture
    elif isinstance(raw_has_fracture, str):
        lowered = raw_has_fracture.strip().lower()
        if not lowered:
            parsed_has_fracture = None
        elif lowered in {"true", "1", "yes"}:
            parsed_has_fracture = True
        elif lowered in {"false", "0", "no"}:
            parsed_has_fracture = False
        else:
            raise ValueError(f"invalid has_fracture value: {raw_has_fracture!r}")
    else:
        raise ValueError(f"invalid has_fracture value: {raw_has_fracture!r}")

    if parsed_has_fracture is not None:
        has_fracture: bool | None = parsed_has_fracture
    elif not source_type:
        raise ValueError(
            "annotation row is missing ground-truth label (has_fracture/source_type)"
        )
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
            row.get("fracture_time", row.get("break_time", row.get("断裂时间点"))),
            field_name="fracture_time",
        ),
        "duration": _optional_number(
            row.get("duration", row.get("duration_seconds", row.get("视频时长"))),
            field_name="duration",
        ),
    }


def _optional_number(value: Any, *, field_name: str = "number") -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"invalid numeric value for {field_name}: {value!r}")
    if isinstance(value, (int, float)):
        parsed = float(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = float(text.removesuffix("s").strip())
        except ValueError as exc:
            raise ValueError(
                f"invalid numeric value for {field_name}: {value!r}"
            ) from exc
    else:
        raise ValueError(f"invalid numeric value for {field_name}: {value!r}")
    if not math.isfinite(parsed):
        raise ValueError(f"invalid numeric value for {field_name}: {value!r}")
    return parsed


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
            2 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
    return sum(scores) / len(scores) if scores else None


def _time_hit(gt: dict[str, Any], pred: dict[str, Any]) -> bool | None:
    timestamp = gt.get("fracture_time")
    duration = gt.get("duration")
    interval = pred.get("time_range")
    if not isinstance(timestamp, (int, float)) or not isinstance(
        duration, (int, float)
    ):
        return None
    if not isinstance(interval, list) or len(interval) != 2:
        return False
    tolerance = max(1.0, float(duration) * 0.05)
    return (
        float(interval[0]) - tolerance
        <= float(timestamp)
        <= float(interval[1]) + tolerance
    )


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
        hit for gt, pred in positives if (hit := _time_hit(gt, pred)) is not None
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
        "has_fracture_accuracy": sum(presence_hits) / len(presence_hits)
        if presence_hits
        else None,
        "fracture_recall": (
            sum(pred.get("has_fracture") is True for _, pred in positives)
            / len(positives)
            if positives
            else None
        ),
        "no_fracture_recall": (
            sum(pred.get("has_fracture") is False for _, pred in negatives)
            / len(negatives)
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


def load_annotation_rows(
    annotations_csv: str | Path,
    *,
    allowed_video_ids: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Load and validate an annotation CSV with fail-closed schema and set checks."""
    annotations: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    with Path(annotations_csv).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        if not fieldnames:
            raise ValueError("annotation CSV is missing header")
        if any(not isinstance(name, str) or not name.strip() for name in fieldnames):
            raise ValueError("annotation CSV contains blank column name")
        if len(set(fieldnames)) != len(fieldnames):
            duplicates = sorted(
                name for name, count in Counter(fieldnames).items() if count > 1
            )
            raise ValueError(
                f"annotation CSV contains duplicate column names: {duplicates}"
            )
        if not any(col in fieldnames for col in ANNOTATION_ID_COLUMNS):
            raise ValueError(
                "annotation CSV is missing required ID column "
                f"(expected one of {ANNOTATION_ID_COLUMNS})"
            )
        if not any(col in fieldnames for col in ANNOTATION_LABEL_COLUMNS):
            raise ValueError(
                "annotation CSV is missing required ground-truth label column "
                f"(expected one of {ANNOTATION_LABEL_COLUMNS})"
            )

        for line_no, row in enumerate(reader, start=2):
            if None in row or any(value is None for value in row.values()):
                raise ValueError(
                    f"annotation CSV row {line_no} column count does not match header"
                )
            video_id = str(
                row.get("video_id") or row.get("video") or row.get("id") or ""
            ).strip()
            if not video_id:
                raise ValueError(f"annotation row {line_no} is missing video_id")
            if video_id in seen_ids:
                raise ValueError(f"duplicate annotation video_id: {video_id}")
            seen_ids.add(video_id)
            if allowed_video_ids is not None and video_id not in allowed_video_ids:
                continue
            row["video_id"] = video_id
            annotations[video_id] = row

    if not seen_ids:
        raise ValueError("annotation CSV contains no data rows")
    if allowed_video_ids is not None and set(annotations) != allowed_video_ids:
        missing = sorted(allowed_video_ids - set(annotations))
        raise ValueError(
            f"annotation/input identity mismatch: missing video_ids={missing}"
        )
    return annotations


def load_scoring_records(
    annotations_csv: str | Path,
    results_root: str | Path,
    *,
    allowed_video_ids: set[str] | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Join source CSV rows to immutable batch results by exact video_id."""
    annotations = load_annotation_rows(
        annotations_csv,
        allowed_video_ids=allowed_video_ids,
    )

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
