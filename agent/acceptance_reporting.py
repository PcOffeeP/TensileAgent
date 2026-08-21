"""Deterministic diagnostic reporting for completed Stage G results."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from agent.scoring_v4_1 import FRACTURE_MECHANISMS


PRESENCE_LABELS = ("fracture", "no_fracture")
PRESENCE_PREDICTIONS = ("fracture", "no_fracture", "unrecognized", "invalid")
MECHANISM_LABELS = tuple(sorted(FRACTURE_MECHANISMS))
SITE_LABELS = ("inside_gauge", "outside_gauge_non_root", "grip_root")


def _empty_matrix(
    truth_labels: Iterable[str],
    prediction_labels: Iterable[str],
) -> dict[str, dict[str, int]]:
    predictions = tuple(prediction_labels)
    return {
        truth: {prediction: 0 for prediction in predictions} for truth in truth_labels
    }


def _presence_prediction(prediction: dict[str, Any]) -> str:
    value = prediction.get("has_fracture")
    if value is True:
        return "fracture"
    if value is False:
        return "no_fracture"
    if prediction.get("status") == "unrecognized":
        return "unrecognized"
    return "invalid"


def _time_hit(
    truth: dict[str, Any],
    prediction: dict[str, Any],
) -> bool | None:
    timestamp = truth.get("fracture_time")
    duration = truth.get("duration")
    interval = prediction.get("time_range")
    if not isinstance(timestamp, (int, float)) or not isinstance(
        duration,
        (int, float),
    ):
        return None
    if not isinstance(interval, list) or len(interval) != 2:
        return False
    tolerance = max(1.0, float(duration) * 0.05)
    try:
        return (
            float(interval[0]) - tolerance
            <= float(timestamp)
            <= float(interval[1]) + tolerance
        )
    except (TypeError, ValueError):
        return False


def build_diagnostic_report(
    records: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    """Build confusion matrices and a compact failure index."""
    presence = _empty_matrix(PRESENCE_LABELS, PRESENCE_PREDICTIONS)
    mechanism = _empty_matrix(
        MECHANISM_LABELS,
        (*MECHANISM_LABELS, "missing_or_other"),
    )
    site = _empty_matrix(SITE_LABELS, (*SITE_LABELS, "missing_or_other"))
    failures: list[dict[str, Any]] = []
    special_cases: list[dict[str, Any]] = []

    for truth, prediction in records:
        video_id = str(truth.get("video_id") or prediction.get("video_id"))
        special_case = truth.get("special_case")
        if special_case is not None:
            correct = (
                prediction.get("status") == "unrecognized"
                and prediction.get("special_case") == special_case
            )
            special_cases.append(
                {
                    "video_id": video_id,
                    "special_case": special_case,
                    "correct": correct,
                }
            )
            if not correct:
                failures.append(
                    {
                        "video_id": video_id,
                        "failed_components": ["special_case"],
                    }
                )
            continue

        truth_presence = (
            "fracture" if truth.get("has_fracture") is True else "no_fracture"
        )
        prediction_presence = _presence_prediction(prediction)
        presence[truth_presence][prediction_presence] += 1
        failed_components: list[str] = []
        if truth_presence != prediction_presence:
            failed_components.append("has_fracture")
        if truth.get("has_fracture") is True:
            time_hit = _time_hit(truth, prediction)
            if time_hit is False:
                failed_components.append("time")
            truth_mechanism = truth.get("fracture_mechanism")
            if truth_mechanism in MECHANISM_LABELS:
                predicted_mechanism = prediction.get("fracture_type")
                if predicted_mechanism not in MECHANISM_LABELS:
                    predicted_mechanism = "missing_or_other"
                mechanism[truth_mechanism][predicted_mechanism] += 1
                if predicted_mechanism != truth_mechanism:
                    failed_components.append("mechanism")
            truth_site = truth.get("fracture_site")
            if truth_site in SITE_LABELS:
                predicted_site = prediction.get("location")
                if predicted_site not in SITE_LABELS:
                    predicted_site = "missing_or_other"
                site[truth_site][predicted_site] += 1
                if predicted_site != truth_site:
                    failed_components.append("site")
        if failed_components:
            failures.append(
                {
                    "video_id": video_id,
                    "failed_components": failed_components,
                }
            )

    return {
        "schema_version": "tensile-agent/stage-g-diagnostic-report/v1",
        "video_count": len(records),
        "presence_confusion_matrix": presence,
        "mechanism_confusion_matrix": mechanism,
        "site_confusion_matrix": site,
        "failure_sample_count": len(failures),
        "failure_sample_index": failures,
        "special_case_results": special_cases,
    }


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(fraction * len(ordered)) - 1)
    return ordered[rank]


def summarize_batch_timing(
    results_root: str | Path,
    expected_video_ids: set[str],
) -> dict[str, Any]:
    """Summarize recorded per-task wall times without reading predictions."""
    root = Path(results_root)
    durations: dict[str, float] = {}
    starts: list[datetime] = []
    finishes: list[datetime] = []
    import json

    for video_id in sorted(expected_video_ids):
        record = json.loads(
            (root / video_id / "result.json").read_text(encoding="utf-8")
        )
        started = _parse_timestamp(record.get("started_at"))
        finished = _parse_timestamp(record.get("finished_at"))
        if started is None or finished is None or finished < started:
            raise ValueError(f"invalid Stage G timing record: {video_id}")
        starts.append(started)
        finishes.append(finished)
        durations[video_id] = (finished - started).total_seconds()
    wall_seconds = (max(finishes) - min(starts)).total_seconds()
    values = list(durations.values())
    return {
        "schema_version": "tensile-agent/stage-g-timing-report/v1",
        "video_count": len(values),
        "wall_seconds": wall_seconds,
        "wall_throughput_videos_per_second": (
            len(values) / wall_seconds if wall_seconds > 0 else None
        ),
        "task_duration_seconds": {
            "minimum": min(values) if values else None,
            "median": _percentile(values, 0.5),
            "p95": _percentile(values, 0.95),
            "maximum": max(values) if values else None,
        },
        "per_video_duration_seconds": durations,
    }
