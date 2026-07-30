"""Pure strategy definitions and reducers for the frozen Agent A/B protocol."""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from agent.schema import V4_1_FRACTURE_MECHANISMS
from agent.v4_1_evidence import V41EventBounds


STRATEGY_AB_SCHEMA = "tensile-agent/strategy-ab/v1"
DIAGNOSTIC_30_IDS = (
    "video_0001",
    "video_0002",
    "video_0003",
    "video_0004",
    "video_0005",
    "video_0006",
    "video_0007",
    "video_0008",
    "video_0009",
    "video_0010",
    "video_0014",
    "video_0017",
    "video_0025",
    "video_0026",
    "video_0027",
    "video_0033",
    "video_0034",
    "video_0040",
    "video_0042",
    "video_0049",
    "video_0052",
    "video_0054",
    "video_0058",
    "video_0066",
    "video_0069",
    "video_0076",
    "video_0083",
    "video_0096",
    "video_0102",
    "video_0106",
)
POSITIVE_STATES = {"发生断裂", "已断裂"}
NEGATIVE_STATES = {"未断裂", "临界未断裂"}
SITE_VALUES = {"inside_gauge", "outside_gauge_non_root", "grip_root"}


def fixed_scan_ranges(duration: float) -> list[list[float]]:
    """Return the frozen ten-call full-video and D/4 overlap schedule."""
    duration = float(duration)
    if duration <= 0:
        raise ValueError("duration must be positive")
    ranges = [[0.0, duration]]
    # Preserve the Agent's five no-fracture coverage windows first.
    for start_numerator in (0, 6, 12, 18, 24):
        ranges.append(
            [
                duration * start_numerator / 32.0,
                duration * (start_numerator + 8) / 32.0,
            ]
        )
    # Fill the four objective gaps to form the nine-window dense schedule.
    for start_numerator in (3, 9, 15, 21):
        ranges.append(
            [
                duration * start_numerator / 32.0,
                duration * (start_numerator + 8) / 32.0,
            ]
        )
    return ranges


def coverage_ranges(duration: float) -> list[list[float]]:
    """Return the five frozen no-fracture coverage windows."""
    return fixed_scan_ranges(duration)[1:6]


def _same_range(left: Any, right: Any, epsilon: float = 1e-6) -> bool:
    return (
        isinstance(left, list)
        and isinstance(right, list)
        and len(left) == len(right) == 2
        and abs(float(left[0]) - float(right[0])) <= epsilon
        and abs(float(left[1]) - float(right[1])) <= epsilon
    )


def _legal_output(round_record: dict[str, Any]) -> dict[str, Any] | None:
    output = round_record.get("model_output")
    if (
        round_record.get("ok") is True
        and round_record.get("validation_error") is None
        and isinstance(output, dict)
    ):
        return output
    return None


def _vote(values: Iterable[Any], valid_values: set[str]) -> str | None:
    filtered = [value for value in values if value in valid_values]
    if len(filtered) < 2:
        return None
    ranked = Counter(filtered).most_common()
    if ranked[0][1] < 2:
        return None
    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return None
    return ranked[0][0]


def map_single_call(round_record: dict[str, Any]) -> dict[str, Any]:
    """Map strategy A's raw single-clip V4.1 output without Agent gates."""
    output = _legal_output(round_record)
    if (
        output is None
        or output.get("clip_state") == "无法判断"
        or output.get("special_case") is not None
    ):
        status = "unrecognized"
    elif output.get("clip_state") in POSITIVE_STATES:
        status = "fracture"
    else:
        status = "no_fracture"
    return {
        "status": status,
        "has_fracture": (
            True if status == "fracture" else False if status == "no_fracture" else None
        ),
        "time_range": None,
        "fracture_type": (
            output.get("fracture_mechanism")
            if output is not None and status == "fracture"
            else None
        ),
        "location": (
            output.get("fracture_site")
            if output is not None and status == "fracture"
            else None
        ),
        "special_case": output.get("special_case") if output is not None else None,
    }


def reduce_fixed_scan(
    rounds: list[dict[str, Any]],
    *,
    duration: float,
    tolerance_seconds: float = 1.0,
) -> dict[str, Any]:
    """Reduce strategy B rounds with the same public evidence thresholds as C."""
    bounds = V41EventBounds(0.0, float(duration))
    positives: list[dict[str, Any]] = []
    legal_rounds: list[dict[str, Any]] = []
    required_coverage = coverage_ranges(duration)
    coverage_index = 0
    in_negative_coverage = False
    for index, round_record in enumerate(rounds):
        output = _legal_output(round_record)
        if output is None:
            continue
        legal_rounds.append(round_record)
        state = output.get("clip_state")
        sample_range = round_record.get("sample_range")
        if state in POSITIVE_STATES:
            positives.append(round_record)
        # A global ordinary negative starts coverage but does not manufacture
        # an event boundary at the end of the whole video.
        if index == 0 and state == "未断裂":
            in_negative_coverage = True
            continue
        if (
            in_negative_coverage
            and coverage_index < len(required_coverage)
            and state == "未断裂"
            and _same_range(sample_range, required_coverage[coverage_index])
        ):
            coverage_index += 1
            continue
        if state in POSITIVE_STATES or state == "临界未断裂":
            in_negative_coverage = False
        if state in {"未断裂", "临界未断裂", "发生断裂", "已断裂", "无法判断"}:
            bounds.apply(state, sample_range)

    local_positives = [
        item
        for item in positives
        if (
            isinstance(item.get("sample_range"), list)
            and float(item["sample_range"][1]) - float(item["sample_range"][0])
            < float(duration) - 1e-9
        )
    ]
    fracture_confirmed = len(positives) >= 2 and bool(local_positives)
    special_case = _vote(
        (
            (_legal_output(item) or {}).get("special_case")
            for item in legal_rounds
        ),
        {"未夹紧", "视频异常"},
    )
    complete_negative_coverage = all(
        any(
            _same_range(item.get("sample_range"), expected)
            and (_legal_output(item) or {}).get("clip_state") == "未断裂"
            for item in legal_rounds
        )
        for expected in required_coverage
    )

    if special_case is not None:
        status = "unrecognized"
    elif fracture_confirmed:
        status = "fracture"
    elif complete_negative_coverage and not positives:
        status = "no_fracture"
    else:
        status = "unrecognized"

    return {
        "status": status,
        "has_fracture": (
            True if status == "fracture" else False if status == "no_fracture" else None
        ),
        "time_range": (
            bounds.interval
            if status == "fracture" and bounds.publishable(tolerance_seconds)
            else None
        ),
        "fracture_type": (
            _vote(
                (
                    (_legal_output(item) or {}).get("fracture_mechanism")
                    for item in positives
                ),
                set(V4_1_FRACTURE_MECHANISMS),
            )
            if status == "fracture"
            else None
        ),
        "location": (
            _vote(
                (
                    (_legal_output(item) or {}).get("fracture_site")
                    for item in positives
                ),
                SITE_VALUES,
            )
            if status == "fracture"
            else None
        ),
        "special_case": special_case,
        "event_bounds": bounds.interval,
        "event_bounds_conflicted": bounds.unresolved_conflict,
        "positive_round_count": len(positives),
        "local_positive_round_count": len(local_positives),
        "complete_negative_coverage": complete_negative_coverage,
        "request_count": len(rounds),
        "valid_response_count": len(legal_rounds),
    }
