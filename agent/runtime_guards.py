"""Pure, replayable evidence admissibility and termination verdict guards."""

from __future__ import annotations

from typing import Any

from agent.schema import FractureType

VALID_UNRECOGNIZED_REASONS = frozenset(
    {
        "video_anomaly",
        "not_clamped",
        "conflicting_results",
        "invalid_model_output",
        "insufficient_confidence",
        "incomplete_coverage",
        "max_rounds",
        "visual_indeterminate",
        "budget_exhausted",
    }
)


def same_range(left: Any, right: Any, epsilon: float = 1e-6) -> bool:
    """Return True when ``left`` and ``right`` are two-element numeric ranges within ``epsilon``."""
    return (
        isinstance(left, list)
        and isinstance(right, list)
        and len(left) == len(right) == 2
        and abs(float(left[0]) - float(right[0])) <= epsilon
        and abs(float(left[1]) - float(right[1])) <= epsilon
    )


def sample_range_is_local(sample_range: Any, duration: float) -> bool:
    """Return True when ``sample_range`` is strictly narrower than ``duration``."""
    return (
        isinstance(sample_range, list)
        and len(sample_range) == 2
        and float(sample_range[1]) - float(sample_range[0]) < float(duration) - 1e-9
    )


def is_full_video_range(sample_range: Any, duration: float, epsilon: float = 1e-6) -> bool:
    """Return True when ``sample_range`` covers ``[0.0, duration]`` within ``epsilon``."""
    dur = float(duration)
    return dur > 0.0 and same_range(sample_range, [0.0, dur], epsilon=epsilon)


def coverage_ranges(duration: float) -> list[list[float]]:
    """Return the five fixed D/4 overlapping windows required after a global negative."""
    dur = float(duration)
    return [
        [dur * start / 16.0, dur * (start + 4) / 16.0]
        for start in (0, 3, 6, 9, 12)
    ]


def round_has_fracture(entry: dict[str, Any]) -> bool:
    """Safely check whether a history entry has a legal positive fracture prediction."""
    result = entry.get("result", {})
    model_output = result.get("model_output")
    return (
        result.get("ok") is True
        and isinstance(model_output, dict)
        and (
            model_output.get("has_fracture", False) is True
            or model_output.get("clip_state") in {"发生断裂", "已断裂"}
        )
    )


def round_is_local_fracture(entry: dict[str, Any], duration: float) -> bool:
    """Require fracture evidence to come from a genuine local inspection."""
    if not round_has_fracture(entry):
        return False
    result = entry.get("result", {})
    return sample_range_is_local(result.get("sample_range"), duration)


def has_complete_no_fracture_coverage(
    history: list[dict[str, Any]],
    *,
    duration: float,
    visual_contract_version: str | None,
    coverage_start_index: int | None,
) -> bool:
    """Validate five fixed windows from recorded, legal model results."""
    expected_windows = coverage_ranges(duration)
    if visual_contract_version == "tensile-vlm/v4.1":
        if any(round_has_fracture(entry) for entry in history):
            return False
        if (
            coverage_start_index is None
            or coverage_start_index < 0
            or coverage_start_index >= len(history)
        ):
            return False
        initiator = history[coverage_start_index].get("result", {})
        initiator_output = initiator.get("model_output") or {}
        if not (
            initiator.get("ok") is True
            and initiator_output.get("clip_state") == "未断裂"
            and is_full_video_range(initiator.get("sample_range"), duration)
        ):
            return False
        coverage_entries = history[coverage_start_index + 1 :]
        for expected in expected_windows:
            matched = any(
                entry.get("result", {}).get("ok") is True
                and same_range(entry.get("result", {}).get("sample_range"), expected)
                and (entry.get("result", {}).get("model_output") or {}).get(
                    "clip_state"
                )
                == "未断裂"
                for entry in coverage_entries
            )
            if not matched:
                return False
        return True

    for expected in expected_windows:
        matched = False
        for entry in history:
            result = entry.get("result", {})
            output = result.get("model_output") or {}
            if (
                result.get("ok") is True
                and same_range(result.get("sample_range"), expected)
                and (
                    (
                        output.get("has_fracture") is False
                        and output.get("type") == FractureType.NO_FRACTURE
                    )
                    or output.get("clip_state") == "未断裂"
                )
            ):
                matched = True
                break
        if not matched:
            return False
    return True


def has_consistent_special_recheck(
    history: list[dict[str, Any]],
    *,
    reason: str,
    visual_contract_version: str | None,
) -> bool:
    """Require two matching anomaly/not-clamped results on the same range."""
    matches: list[tuple[list[float], tuple[Any, Any]]] = []
    is_v4_1 = visual_contract_version == "tensile-vlm/v4.1"
    for entry in history:
        result = entry.get("result", {})
        if result.get("ok") is not True:
            continue
        output = result.get("model_output") or {}
        if is_v4_1 or "clip_state" in output:
            clip_state = output.get("clip_state")
            special_case = output.get("special_case")
            if clip_state != "无法判断":
                continue
            if reason == "not_clamped":
                if special_case != "未夹紧":
                    continue
            elif reason == "video_anomaly":
                if special_case != "视频异常":
                    continue
            elif reason == "visual_indeterminate":
                if special_case in {"未夹紧", "视频异常"}:
                    continue
            else:
                continue
            matches.append((result.get("sample_range"), (clip_state, special_case)))
        else:
            is_match = (
                reason in {"video_anomaly", "visual_indeterminate"}
                and "has_fracture" in output
                and output.get("has_fracture") is None
            ) or (
                reason == "not_clamped"
                and output.get("type") == FractureType.NOT_CLAMPED
            )
            if is_match:
                matches.append(
                    (
                        result.get("sample_range"),
                        (output.get("has_fracture"), output.get("type")),
                    )
                )
    for index, (sample_range, signature) in enumerate(matches):
        if any(
            same_range(sample_range, other_range) and signature == other_signature
            for other_range, other_signature in matches[index + 1 :]
        ):
            return True
    return False


def evaluate_unrecognized_reason(
    reason: Any,
    *,
    history: list[dict[str, Any]],
    round_idx: int,
    max_rounds: int,
    conflict_count: int,
    unresolved_conflict: bool,
    special_recheck_ok: bool | None = None,
    visual_contract_version: str | None = None,
) -> tuple[bool, str]:
    """Validate an ``unrecognized`` termination proposal against observed facts."""
    if reason not in VALID_UNRECOGNIZED_REASONS:
        return False, (
            f"unrecognized_reason 无效: {reason}，"
            f"须为 {sorted(VALID_UNRECOGNIZED_REASONS)}"
        )
    if reason in {"video_anomaly", "visual_indeterminate", "not_clamped"}:
        passed = (
            special_recheck_ok
            if special_recheck_ok is not None
            else has_consistent_special_recheck(
                history,
                reason=str(reason),
                visual_contract_version=visual_contract_version,
            )
        )
        if not passed:
            return False, "视觉不可判定或未夹紧必须在同一区间得到两次一致结果"
    elif reason in {"max_rounds", "budget_exhausted"}:
        if round_idx + 1 < max_rounds and len(history) < max_rounds:
            return (
                False,
                "当前迭代预算尚未耗尽，不能以 max_rounds/budget_exhausted 提前终止",
            )
    elif reason == "conflicting_results":
        if not (conflict_count > 0 or unresolved_conflict):
            return False, "当前尚未观察到不可调和的冲突证据，不能以 conflicting_results 终止"
    elif reason == "invalid_model_output":
        has_validation_error = any(
            entry.get("result", {}).get("validation_error") is not None
            for entry in history
        )
        if not has_validation_error:
            return False, "当前尚未观察到非法视觉输出，不能以 invalid_model_output 终止"
    elif reason in {"insufficient_confidence", "incomplete_coverage"}:
        if not history:
            return False, "尚未执行任何视觉观察，不能以证据不足或覆盖不全终止"
    return True, "模型明确报告无法识别"
