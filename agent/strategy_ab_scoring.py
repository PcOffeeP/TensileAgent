"""Metrics and paired comparisons for the frozen strategy A/B experiment."""

from __future__ import annotations

import random
from collections import Counter
from typing import Any, Callable


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _time_contains(
    prediction: dict[str, Any], timestamp: Any, margin: float = 0.0
) -> bool:
    interval = prediction.get("time_range")
    return (
        isinstance(timestamp, (int, float))
        and isinstance(interval, list)
        and len(interval) == 2
        and float(interval[0]) - margin
        <= float(timestamp)
        <= float(interval[1]) + margin
    )


def score_method(
    records: list[tuple[dict[str, Any], dict[str, Any], int]],
) -> dict[str, Any]:
    """Score one method with explicit availability and fixed denominators."""
    normal = [
        (gt, pred, calls) for gt, pred, calls in records if gt["special_case"] is None
    ]
    positives = [item for item in normal if item[0]["has_fracture"] is True]
    negatives = [item for item in normal if item[0]["has_fracture"] is False]
    tp = sum(pred.get("has_fracture") is True for gt, pred, _ in positives)
    fn = len(positives) - tp
    tn = sum(pred.get("has_fracture") is False for gt, pred, _ in negatives)
    fp = sum(pred.get("has_fracture") is True for gt, pred, _ in negatives)
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )
    available_times = [
        (gt, pred)
        for gt, pred, _ in positives
        if isinstance(pred.get("time_range"), list)
    ]
    time_evaluable = [
        (gt, pred)
        for gt, pred, _ in positives
        if isinstance(gt.get("fracture_time"), (int, float))
    ]
    available_evaluable = [
        (gt, pred)
        for gt, pred in time_evaluable
        if isinstance(pred.get("time_range"), list)
    ]
    mechanism_eligible = [
        (gt, pred)
        for gt, pred, _ in positives
        if gt.get("fracture_mechanism") is not None
    ]
    site_eligible = [
        (gt, pred) for gt, pred, _ in positives if gt.get("fracture_site") is not None
    ]
    specials = [(gt, pred) for gt, pred, _ in records if gt["special_case"] is not None]
    return {
        "n": len(records),
        "presence": {
            "accuracy": (tp + tn) / len(normal) if normal else None,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "specificity": tn / len(negatives) if negatives else None,
            "abstention_rate": (
                sum(pred.get("has_fracture") is None for _, pred, _ in normal)
                / len(normal)
                if normal
                else None
            ),
            "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "denominator": len(normal),
        },
        "time": {
            "availability": len(available_times) / len(positives)
            if positives
            else None,
            "strict_hit_rate_all_positives": (
                sum(
                    _time_contains(pred, gt.get("fracture_time"))
                    for gt, pred in time_evaluable
                )
                / len(time_evaluable)
                if time_evaluable
                else None
            ),
            "within_1s_rate_all_positives": (
                sum(
                    _time_contains(pred, gt.get("fracture_time"), 1.0)
                    for gt, pred in time_evaluable
                )
                / len(time_evaluable)
                if time_evaluable
                else None
            ),
            "strict_hit_rate_when_available": (
                sum(
                    _time_contains(pred, gt.get("fracture_time"))
                    for gt, pred in available_evaluable
                )
                / len(available_evaluable)
                if available_evaluable
                else None
            ),
            "availability_denominator": len(positives),
            "accuracy_denominator": len(time_evaluable),
        },
        "mechanism": {
            "availability": (
                sum(
                    pred.get("fracture_type") is not None
                    for _, pred in mechanism_eligible
                )
                / len(mechanism_eligible)
                if mechanism_eligible
                else None
            ),
            "accuracy": (
                sum(
                    pred.get("fracture_type") == gt["fracture_mechanism"]
                    for gt, pred in mechanism_eligible
                )
                / len(mechanism_eligible)
                if mechanism_eligible
                else None
            ),
            "denominator": len(mechanism_eligible),
        },
        "site": {
            "availability": (
                sum(pred.get("location") is not None for _, pred in site_eligible)
                / len(site_eligible)
                if site_eligible
                else None
            ),
            "accuracy": (
                sum(
                    pred.get("location") == gt["fracture_site"]
                    for gt, pred in site_eligible
                )
                / len(site_eligible)
                if site_eligible
                else None
            ),
            "denominator": len(site_eligible),
        },
        "special_case": {
            "accuracy": (
                sum(
                    pred.get("special_case") == gt["special_case"]
                    for gt, pred in specials
                )
                / len(specials)
                if specials
                else None
            ),
            "denominator": len(specials),
        },
        "efficiency": {
            "mean_requests": _mean([float(calls) for _, _, calls in records]),
            "total_requests": sum(calls for _, _, calls in records),
            "request_count_distribution": dict(
                Counter(calls for _, _, calls in records)
            ),
        },
    }


def paired_bootstrap_delta(
    records_b: list[tuple[dict[str, Any], dict[str, Any], int]],
    records_c: list[tuple[dict[str, Any], dict[str, Any], int]],
    *,
    score: Callable[[dict[str, Any], dict[str, Any]], float],
    seed: int = 42,
    iterations: int = 10000,
) -> dict[str, Any]:
    """Return B-minus-C paired bootstrap delta and a percentile 95% CI."""
    if len(records_b) != len(records_c) or not records_b:
        raise ValueError("paired records must be non-empty and have equal length")
    differences = [
        score(gt_b, pred_b) - score(gt_c, pred_c)
        for (gt_b, pred_b, _), (gt_c, pred_c, _) in zip(records_b, records_c)
    ]
    rng = random.Random(seed)
    n = len(differences)
    samples = sorted(
        sum(differences[rng.randrange(n)] for _ in range(n)) / n
        for _ in range(iterations)
    )
    return {
        "delta_b_minus_c": sum(differences) / n,
        "ci95": [
            samples[int(iterations * 0.025)],
            samples[min(iterations - 1, int(iterations * 0.975))],
        ],
        "seed": seed,
        "iterations": iterations,
    }


def presence_correct(gt: dict[str, Any], prediction: dict[str, Any]) -> float:
    """Return a fixed-denominator presence correctness indicator."""
    if gt.get("special_case") is not None:
        return float(prediction.get("special_case") == gt["special_case"])
    return float(prediction.get("has_fracture") == gt.get("has_fracture"))


def time_within_1s(gt: dict[str, Any], prediction: dict[str, Any]) -> float:
    """Return a positive-only time correctness indicator; other rows score zero."""
    if gt.get("has_fracture") is not True:
        return 0.0
    return float(_time_contains(prediction, gt.get("fracture_time"), 1.0))
