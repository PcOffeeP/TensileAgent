"""Frozen common-metric scoring for the post-Stage-G V2 comparison."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from agent.acceptance_batch import (
    load_acceptance_manifest,
    load_bound_input_list,
    sha256_file,
)
from agent.scoring_v4_1 import (
    FRACTURE_MECHANISMS,
    normalize_ground_truth,
)
from agent.v2_comparison_batch import load_v2_comparison_manifest


COMMON_NUMERIC_METRICS = (
    "has_fracture_accuracy",
    "fracture_recall",
    "no_fracture_recall",
    "time_hit_rate",
    "mechanism_macro_f1",
    "coarse_site_macro_f1",
    "joint_common_success_rate",
)


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _macro_f1(
    pairs: Iterable[tuple[Any, Any]],
    labels: set[Any],
) -> float | None:
    rows = list(pairs)
    scores: list[float] = []
    for label in sorted(labels):
        tp = sum(gt == label and pred == label for gt, pred in rows)
        fp = sum(gt != label and pred == label for gt, pred in rows)
        fn = sum(gt == label and pred != label for gt, pred in rows)
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


def _coarse_site(value: Any) -> str | None:
    if value == "inside_gauge":
        return "inside_gauge"
    if value in {
        "outside_gauge",
        "outside_gauge_non_root",
        "grip_root",
    }:
        return "outside_gauge"
    return None


def adapt_prediction(
    prediction: dict[str, Any],
    schema_version: str,
) -> dict[str, Any]:
    """Project V2 and V4.1 public outputs into their common taxonomy."""
    if prediction.get("schema_version") != schema_version:
        raise ValueError("comparison prediction schema mismatch")
    fracture_type = prediction.get("fracture_type")
    mechanism = {
        "齐根断裂": None,
        "界面脱粘、齐根断裂": "界面脱粘",
        "脆性断裂、齐根断裂": "脆性断裂",
    }.get(fracture_type, fracture_type)
    if mechanism not in FRACTURE_MECHANISMS:
        mechanism = None
    special_case = prediction.get("special_case")
    if schema_version == "tensile-agent/result/v2":
        special_case = {
            "not_clamped": "未夹紧",
            "video_anomaly": "视频异常",
        }.get(prediction.get("unrecognized_reason"))
    return {
        "video_id": prediction.get("video_id"),
        "status": prediction.get("status"),
        "has_fracture": prediction.get("has_fracture"),
        "time_range": prediction.get("time_range"),
        "fracture_mechanism": mechanism,
        "coarse_site": _coarse_site(prediction.get("location")),
        "special_case": special_case,
    }


def _time_hit(truth: dict[str, Any], prediction: dict[str, Any]) -> bool | None:
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
    return (
        float(interval[0]) - tolerance
        <= float(timestamp)
        <= float(interval[1]) + tolerance
    )


def score_common(
    records: list[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    """Score only metrics supported by both public result schemas."""
    normal = [(gt, pred) for gt, pred in records if gt["special_case"] is None]
    positives = [(gt, pred) for gt, pred in normal if gt["has_fracture"] is True]
    negatives = [(gt, pred) for gt, pred in normal if gt["has_fracture"] is False]
    presence = [
        pred["has_fracture"] == gt["has_fracture"] for gt, pred in normal
    ]
    time_hits = [
        hit
        for gt, pred in positives
        if (hit := _time_hit(gt, pred)) is not None
    ]
    mechanism_pairs = [
        (gt["fracture_mechanism"], pred["fracture_mechanism"])
        for gt, pred in positives
        if gt["fracture_mechanism"] is not None
    ]
    coarse_site_pairs = [
        (_coarse_site(gt["fracture_site"]), pred["coarse_site"])
        for gt, pred in positives
        if _coarse_site(gt["fracture_site"]) is not None
    ]
    joint: list[bool] = []
    for gt, pred in normal:
        ok = pred["has_fracture"] == gt["has_fracture"]
        if gt["has_fracture"] is True:
            time_ok = _time_hit(gt, pred)
            ok = (
                ok
                and time_ok is not False
                and (
                    gt["fracture_mechanism"] is None
                    or pred["fracture_mechanism"]
                    == gt["fracture_mechanism"]
                )
                and (
                    _coarse_site(gt["fracture_site"]) is None
                    or pred["coarse_site"]
                    == _coarse_site(gt["fracture_site"])
                )
            )
        joint.append(ok)
    special = [
        (
            gt["special_case"],
            pred["status"] == "unrecognized"
            and pred["special_case"] == gt["special_case"],
        )
        for gt, pred in records
        if gt["special_case"] is not None
    ]
    return {
        "has_fracture_accuracy": sum(presence) / len(presence)
        if presence
        else None,
        "fracture_recall": (
            sum(pred["has_fracture"] is True for _, pred in positives)
            / len(positives)
            if positives
            else None
        ),
        "no_fracture_recall": (
            sum(pred["has_fracture"] is False for _, pred in negatives)
            / len(negatives)
            if negatives
            else None
        ),
        "time_hit_rate": sum(time_hits) / len(time_hits)
        if time_hits
        else None,
        "mechanism_macro_f1": _macro_f1(
            mechanism_pairs,
            FRACTURE_MECHANISMS,
        ),
        "coarse_site_macro_f1": _macro_f1(
            coarse_site_pairs,
            {"inside_gauge", "outside_gauge"},
        ),
        "joint_common_success_rate": sum(joint) / len(joint)
        if joint
        else None,
        "special_case_results": [
            {"special_case": name, "correct": correct}
            for name, correct in special
        ],
        "special_case_counts": dict(Counter(name for name, _ in special)),
        "denominators": {
            "presence": len(normal),
            "fracture": len(positives),
            "no_fracture": len(negatives),
            "time": len(time_hits),
            "mechanism": len(mechanism_pairs),
            "coarse_site": len(coarse_site_pairs),
            "joint_common": len(joint),
            "special_case": len(special),
        },
    }


def load_common_records(
    annotations: str | Path,
    results_root: str | Path,
    *,
    schema_version: str,
    allowed_video_ids: set[str],
    manifest_hash_field: str | None = None,
    expected_manifest_hash: str | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Join a complete result root to annotations under one public schema."""
    import csv

    truth: dict[str, dict[str, Any]] = {}
    with Path(annotations).open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            video_id = str(
                row.get("video_id") or row.get("video") or row.get("id") or ""
            ).strip()
            if video_id not in allowed_video_ids:
                continue
            if video_id in truth:
                raise ValueError(f"duplicate annotation video_id: {video_id}")
            row["video_id"] = video_id
            truth[video_id] = normalize_ground_truth(row)
    if set(truth) != allowed_video_ids:
        raise ValueError("annotation/input identity mismatch")
    root = Path(results_root)
    failures = list(root.glob("*/failure.json"))
    if failures:
        raise ValueError("comparison result root contains failures")
    records: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for video_id in sorted(allowed_video_ids):
        path = root / video_id / "result.json"
        if not path.is_file():
            raise ValueError(f"missing comparison result: {video_id}")
        batch = json.loads(path.read_text(encoding="utf-8"))
        if (
            manifest_hash_field is not None
            and batch.get(manifest_hash_field) != expected_manifest_hash
        ):
            raise ValueError(f"comparison manifest mismatch: {video_id}")
        prediction = batch.get("runner_result", {}).get("result")
        if not isinstance(prediction, dict) or prediction.get(
            "video_id"
        ) != video_id:
            raise ValueError(f"invalid comparison result: {video_id}")
        records.append(
            (truth[video_id], adapt_prediction(prediction, schema_version))
        )
    return records


def build_v4_common_baseline(
    *,
    v4_acceptance_manifest_path: str | Path,
    v4_finalization_manifest_path: str | Path,
    annotations_path: str | Path,
    results_root: str | Path,
) -> dict[str, Any]:
    """Freeze V4.1 common metrics and their exact post-run evidence identity."""
    manifest = load_acceptance_manifest(v4_acceptance_manifest_path)
    finalization_path = Path(v4_finalization_manifest_path).resolve()
    finalization = json.loads(finalization_path.read_text(encoding="utf-8"))
    annotations = Path(annotations_path).resolve()
    if (
        finalization.get("schema_version")
        != "tensile-agent/stage-g-finalization/v1"
        or finalization.get("status") != "scored_awaiting_v2_comparison"
        or finalization.get("inputs", {}).get("manifest_sha256")
        != manifest["_sha256"]
        or finalization.get("inputs", {}).get("annotations_sha256")
        != sha256_file(annotations)
    ):
        raise ValueError("V4.1 finalization identity mismatch")
    for name, expected_hash in finalization.get("artifacts", {}).items():
        artifact = finalization_path.parent / name
        if not artifact.is_file() or sha256_file(artifact) != expected_hash:
            raise ValueError(f"V4.1 finalization artifact mismatch: {name}")

    inputs = load_bound_input_list(manifest, "all_110")
    video_ids = {row["video_id"] for row in inputs}
    root = Path(results_root).resolve()
    result_hashes = {
        video_id: sha256_file(root / video_id / "result.json")
        for video_id in sorted(video_ids)
        if (root / video_id / "result.json").is_file()
    }
    if set(result_hashes) != video_ids:
        raise ValueError("V4.1 result set is incomplete")
    report = score_common(
        load_common_records(
            annotations,
            root,
            schema_version="tensile-agent/result/v4.1",
            allowed_video_ids=video_ids,
            manifest_hash_field="acceptance_manifest_sha256",
            expected_manifest_hash=manifest["_sha256"],
        )
    )
    identity = {
        "v4_acceptance_manifest_sha256": manifest["_sha256"],
        "v4_finalization_manifest_sha256": sha256_file(finalization_path),
        "annotations_sha256": sha256_file(annotations),
        "result_set_sha256": _canonical_hash(result_hashes),
        "video_count": len(video_ids),
    }
    return {
        "schema_version": "tensile-agent/v4-common-baseline/v1",
        "baseline_id": "v4-common-baseline-" + _canonical_hash(identity)[:12],
        **identity,
        "report": report,
    }


def compare_common_reports(
    v4_report: dict[str, Any],
    v2_report: dict[str, Any],
    *,
    absolute_tolerance: float,
) -> dict[str, Any]:
    """Evaluate pre-frozen non-regression on supported numeric metrics."""
    metrics: dict[str, Any] = {}
    for metric in COMMON_NUMERIC_METRICS:
        v4 = v4_report.get(metric)
        v2 = v2_report.get(metric)
        delta = (
            float(v4) - float(v2)
            if isinstance(v4, (int, float))
            and isinstance(v2, (int, float))
            else None
        )
        metrics[metric] = {
            "v4_1": v4,
            "v2": v2,
            "delta": delta,
            "minimum_delta": -absolute_tolerance,
            "passed": (
                delta is not None
                and (
                    delta >= -absolute_tolerance
                    or math.isclose(
                        delta,
                        -absolute_tolerance,
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                )
            ),
        }
    return {
        "absolute_tolerance": absolute_tolerance,
        "metrics": metrics,
        "passed": all(value["passed"] for value in metrics.values()),
    }


def compare_special_cases(
    v4_report: dict[str, Any],
    v2_report: dict[str, Any],
) -> dict[str, Any]:
    """Apply the pre-run exact special-case comparison policy."""

    def _summary(report: dict[str, Any]) -> tuple[int, int]:
        rows = report.get("special_case_results")
        if not isinstance(rows, list):
            raise ValueError("common report missing special_case_results")
        correct = sum(
            isinstance(row, dict) and row.get("correct") is True
            for row in rows
        )
        return correct, len(rows)

    v4_correct, v4_total = _summary(v4_report)
    v2_correct, v2_total = _summary(v2_report)
    return {
        "policy": (
            "V4.1 must retain exact special-case correctness and may not "
            "underperform V2 on the identical special-case subset."
        ),
        "v4_1": {"correct": v4_correct, "total": v4_total},
        "v2": {"correct": v2_correct, "total": v2_total},
        "same_denominator": v4_total == v2_total,
        "passed": (
            v4_total > 0
            and v4_total == v2_total
            and v4_correct == v4_total
            and v4_correct >= v2_correct
        ),
    }


def validate_v2_result_identity(
    manifest_path: str | Path,
    results_root: str | Path,
) -> dict[str, Any]:
    """Validate completion, immutable identity, schema, and deployment."""
    manifest = load_v2_comparison_manifest(manifest_path)
    inputs = json.loads(
        Path(manifest["input_list"]["path"]).read_text(encoding="utf-8")
    )
    if (
        not isinstance(inputs, list)
        or len(inputs) != manifest["input_list"]["count"]
    ):
        raise ValueError("invalid V2 comparison input list")
    expected: dict[str, str] = {}
    for row in inputs:
        if not isinstance(row, dict):
            raise ValueError("invalid V2 comparison input row")
        video_id = row.get("video_id")
        video_path = row.get("video_path")
        if (
            not isinstance(video_id, str)
            or not video_id
            or video_id in expected
            or not isinstance(video_path, str)
            or not Path(video_path).is_file()
        ):
            raise ValueError("invalid V2 comparison input identity")
        expected[video_id] = video_path
    root = Path(results_root)
    result_ids = {
        path.parent.name for path in root.glob("*/result.json") if path.is_file()
    }
    failure_ids = {
        path.parent.name for path in root.glob("*/failure.json") if path.is_file()
    }
    errors: dict[str, list[str]] = {}
    if result_ids != set(expected) or failure_ids:
        raise ValueError(
            f"incomplete V2 comparison: {len(result_ids)}/{len(expected)}, "
            f"failures={len(failure_ids)}"
        )
    deployment = manifest["service_snapshot"]["deployment_manifest"]
    for video_id in sorted(expected):
        value = json.loads(
            (root / video_id / "result.json").read_text(encoding="utf-8")
        )
        item_errors: list[str] = []
        if (
            value.get("v2_comparison_manifest_sha256")
            != manifest["_sha256"]
            or value.get("video_path") != expected[video_id]
        ):
            item_errors.append("batch identity mismatch")
        runner = value.get("runner_result", {})
        if runner.get("ok") is not True:
            item_errors.append("runner failed")
        if (
            runner.get("runtime_identity", {})
            .get("visual_deployment", {})
            .get("deployment_manifest")
            != deployment
        ):
            item_errors.append("deployment mismatch")
        result = runner.get("result", {})
        if (
            result.get("schema_version") != "tensile-agent/result/v2"
            or result.get("video_id") != video_id
        ):
            item_errors.append("public result identity mismatch")
        if item_errors:
            errors[video_id] = item_errors
    return {
        "schema_version": "tensile-agent/v2-chain-report/v1",
        "v2_comparison_manifest_id": manifest["manifest_id"],
        "v2_comparison_manifest_sha256": manifest["_sha256"],
        "expected_videos": len(expected),
        "successful_videos": len(result_ids),
        "failed_videos": 0,
        "identity_error_count": sum(map(len, errors.values())),
        "errors": errors,
        "passed": not errors,
    }
