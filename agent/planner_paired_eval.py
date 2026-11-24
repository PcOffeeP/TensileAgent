"""Paired evaluation utilities comparing DeterministicPlanner vs LLM planner on the same V4.1 Runtime."""

from __future__ import annotations

import time
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

from agent.interaction import _regex_parse_user_intent
from agent.runner import run_one
from agent.schema import UserIntent
from agent.strategy_ab_scoring import score_method

PLANNER_PAIRED_EVAL_SCHEMA = "tensile-agent/planner-paired-eval/v1"


def _extract_arm_metrics(
    runner_result: dict[str, Any],
    *,
    elapsed_seconds: float,
) -> dict[str, Any]:
    """Extract standardized prediction, real call counts, and failure info from one run_one envelope."""
    ok = runner_result.get("ok") is True
    trace = runner_result.get("evaluation_trace") or {}
    history = trace.get("history") or []
    call_stats = trace.get("call_stats") or {}

    sampling_rounds = len(history)
    if call_stats:
        visual_analysis_calls = int(call_stats.get("visual_analysis_calls", 0))
        visual_evidence_calls = int(call_stats.get("visual_evidence_calls", 0))
        decision_llm_calls = int(call_stats.get("decision_llm_calls", 0))
        deterministic_planner_calls = int(
            call_stats.get("deterministic_planner_calls", 0)
        )
        program_scheduled_rounds = int(call_stats.get("program_scheduled_rounds", 0))
    else:
        # Fallback for synthetic stubs that do not populate call_stats.
        visual_analysis_calls = sum(
            1
            for entry in history
            if (entry.get("result") or {}).get("infra_error", {}).get("stage")
            != "sampling"
        )
        visual_evidence_calls = 0
        program_scheduled_rounds = sum(
            1 for entry in history if entry.get("model") == "program/scheduler"
        )
        deterministic_planner_calls = sum(
            1
            for entry in history
            if str(entry.get("model", "")).startswith("deterministic/")
        )
        decision_llm_calls = max(
            0,
            sampling_rounds - program_scheduled_rounds - deterministic_planner_calls,
        )

    base = {
        "visual_analysis_calls": visual_analysis_calls,
        "visual_evidence_calls": visual_evidence_calls,
        "visual_calls": visual_analysis_calls + visual_evidence_calls,
        "decision_llm_calls": decision_llm_calls,
        "deterministic_planner_calls": deterministic_planner_calls,
        "program_scheduled_rounds": program_scheduled_rounds,
        "sampling_rounds": sampling_rounds,
        "elapsed_seconds": round(float(elapsed_seconds), 4),
    }

    if not ok:
        return {
            "ok": False,
            "error": runner_result.get("error"),
            "prediction": {
                "status": "unrecognized",
                "has_fracture": None,
                "time_range": None,
                "fracture_type": None,
                "location": None,
                "special_case": None,
                "unrecognized_reason": "execution_failed",
            },
            **base,
        }

    result = runner_result.get("result") or {}
    return {
        "ok": True,
        "error": None,
        "prediction": {
            "status": result.get("status"),
            "has_fracture": result.get("has_fracture"),
            "time_range": result.get("time_range"),
            "fracture_type": result.get("fracture_type"),
            "location": result.get("location"),
            "special_case": result.get("special_case"),
            "unrecognized_reason": result.get("unrecognized_reason"),
        },
        **base,
    }


def resolve_shared_intent(
    question: str = "请完整分析这段拉伸试验视频",
    *,
    resolved_intent: UserIntent | None = None,
) -> UserIntent:
    """Resolve the user intent once so both planner arms receive identical intent settings."""
    if resolved_intent is not None:
        return resolved_intent
    return _regex_parse_user_intent(question)


def run_paired_video(
    *,
    video_id: str,
    video_path: str | Path,
    config_path: str | Path,
    work_dir: str | Path,
    question: str = "请完整分析这段拉伸试验视频",
    resolved_intent: UserIntent | None = None,
    llm_backend: str = "local",
    llm_model: str | None = None,
    deterministic_model: str = "v4.1-interval-policy-v1",
    runner_fn: Callable[..., dict[str, Any]] = run_one,
) -> dict[str, Any]:
    """Run deterministic and LLM planners on the exact same video, runtime, and resolved intent."""
    work_root = Path(work_dir)
    shared_intent = resolve_shared_intent(question, resolved_intent=resolved_intent)

    t0 = time.monotonic()
    det_raw = runner_fn(
        video_path=video_path,
        config_path=config_path,
        video_id=video_id,
        work_dir=work_root / "deterministic" / video_id,
        agent_backend="deterministic",
        agent_model=deterministic_model,
        question=question,
        resolved_intent=shared_intent,
        trace_task_id=f"paired-det-{video_id}",
        include_internal_trace=True,
    )
    det_elapsed = time.monotonic() - t0

    t1 = time.monotonic()
    llm_raw = runner_fn(
        video_path=video_path,
        config_path=config_path,
        video_id=video_id,
        work_dir=work_root / "llm" / video_id,
        agent_backend=llm_backend,
        agent_model=llm_model,
        question=question,
        resolved_intent=shared_intent,
        trace_task_id=f"paired-llm-{video_id}",
        include_internal_trace=True,
    )
    llm_elapsed = time.monotonic() - t1

    return {
        "schema_version": PLANNER_PAIRED_EVAL_SCHEMA,
        "video_id": video_id,
        "question": question,
        "shared_intent": shared_intent.model_dump(mode="json"),
        "deterministic": _extract_arm_metrics(det_raw, elapsed_seconds=det_elapsed),
        "llm": _extract_arm_metrics(llm_raw, elapsed_seconds=llm_elapsed),
    }


def _arm_cost_summary(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    arm_rows = [row[arm] for row in rows]
    n = len(arm_rows)
    failures = sum(1 for item in arm_rows if not item.get("ok"))
    visual_analysis_total = sum(int(item.get("visual_analysis_calls", 0)) for item in arm_rows)
    visual_evidence_total = sum(int(item.get("visual_evidence_calls", 0)) for item in arm_rows)
    visual_total = sum(int(item.get("visual_calls", 0)) for item in arm_rows)
    decision_llm_total = sum(int(item.get("decision_llm_calls", 0)) for item in arm_rows)
    det_planner_total = sum(
        int(item.get("deterministic_planner_calls", 0)) for item in arm_rows
    )
    sampling_rounds_total = sum(int(item.get("sampling_rounds", 0)) for item in arm_rows)
    elapsed_total = sum(float(item.get("elapsed_seconds", 0.0)) for item in arm_rows)
    return {
        "videos": n,
        "execution_failures": failures,
        "failure_rate": round(failures / n, 4) if n else None,
        "total_visual_analysis_calls": visual_analysis_total,
        "total_visual_evidence_calls": visual_evidence_total,
        "total_visual_calls": visual_total,
        "mean_visual_calls": round(visual_total / n, 3) if n else None,
        "total_decision_llm_calls": decision_llm_total,
        "mean_decision_llm_calls": round(decision_llm_total / n, 3) if n else None,
        "total_deterministic_planner_calls": det_planner_total,
        "total_sampling_rounds": sampling_rounds_total,
        "total_elapsed_seconds": round(elapsed_total, 4),
        "mean_elapsed_seconds": round(elapsed_total / n, 4) if n else None,
    }


def _exact_fraction(num: int, den: int) -> Fraction | None:
    return Fraction(num, den) if den > 0 else None


def _negative_fp_fraction(score: dict[str, Any]) -> Fraction | None:
    confusion = (score.get("presence") or {}).get("confusion") or {}
    fp = int(confusion.get("fp", 0))
    tn = int(confusion.get("tn", 0))
    return _exact_fraction(fp, fp + tn)


def _recall_fraction(score: dict[str, Any]) -> Fraction | None:
    confusion = (score.get("presence") or {}).get("confusion") or {}
    tp = int(confusion.get("tp", 0))
    fn = int(confusion.get("fn", 0))
    return _exact_fraction(tp, tp + fn)


def _negative_fp_rate(score: dict[str, Any]) -> float | None:
    frac = _negative_fp_fraction(score)
    return float(frac) if frac is not None else None


def decide_default_planner(
    det_score: dict[str, Any],
    llm_score: dict[str, Any],
    det_cost: dict[str, Any],
    llm_cost: dict[str, Any],
    *,
    valid_paired_positives: int | None = None,
    valid_paired_negatives: int | None = None,
    min_evaluable_positives: int = 10,
    min_evaluable_negatives: int = 1,
    recall_tolerance: float = 0.05,
    fp_rate_tolerance: float = 0.05,
    max_failure_rate: float = 0.1,
) -> dict[str, Any]:
    """Apply exact Fraction quality thresholds and failure/cost guardrails."""
    det_n = int(det_cost.get("videos", 0))
    llm_n = int(llm_cost.get("videos", 0))
    det_fail = int(det_cost.get("execution_failures", 0))
    llm_fail = int(llm_cost.get("execution_failures", 0))
    max_fail_frac = Fraction(str(max_failure_rate))

    if (
        (det_n > 0 and Fraction(det_fail, det_n) > max_fail_frac)
        or (llm_n > 0 and Fraction(llm_fail, llm_n) > max_fail_frac)
    ):
        return {
            "recommendation": "keep_current_default",
            "reason": "excessive_execution_failures",
            "det_execution_failures": det_fail,
            "llm_execution_failures": llm_fail,
            "max_failure_rate": max_failure_rate,
        }

    det_conf = (det_score.get("presence") or {}).get("confusion") or {}
    total_positives = int(det_conf.get("tp", 0)) + int(det_conf.get("fn", 0))
    total_negatives = int(det_conf.get("fp", 0)) + int(det_conf.get("tn", 0))
    effective_positives = (
        valid_paired_positives if valid_paired_positives is not None else total_positives
    )
    effective_negatives = (
        valid_paired_negatives if valid_paired_negatives is not None else total_negatives
    )
    det_recall = _recall_fraction(det_score)
    llm_recall = _recall_fraction(llm_score)
    det_fp = _negative_fp_fraction(det_score)
    llm_fp = _negative_fp_fraction(llm_score)

    if (
        effective_positives < min_evaluable_positives
        or det_recall is None
        or llm_recall is None
    ):
        return {
            "recommendation": "keep_current_default",
            "reason": "insufficient_sample_size",
            "valid_paired_positives": effective_positives,
            "min_evaluable_positives": min_evaluable_positives,
        }

    if min_evaluable_negatives > 0 and (
        effective_negatives < min_evaluable_negatives
        or det_fp is None
        or llm_fp is None
    ):
        return {
            "recommendation": "keep_current_default",
            "reason": "insufficient_negative_samples",
            "valid_paired_negatives": effective_negatives,
            "min_evaluable_negatives": min_evaluable_negatives,
        }

    recall_tol = Fraction(str(recall_tolerance))
    fp_tol = Fraction(str(fp_rate_tolerance))
    recall_diff = det_recall - llm_recall
    fp_within_tolerance = (
        True if det_fp is None or llm_fp is None else det_fp <= llm_fp + fp_tol
    )
    det_cheaper = (
        int(det_cost.get("total_decision_llm_calls", 0))
        < int(llm_cost.get("total_decision_llm_calls", 0))
        or float(det_cost.get("total_elapsed_seconds", 0.0))
        < float(llm_cost.get("total_elapsed_seconds", 0.0))
    )

    if recall_diff >= -recall_tol and fp_within_tolerance and det_cheaper:
        return {
            "recommendation": "prefer_deterministic",
            "reason": "within_quality_tolerance_and_lower_cost",
            "recall_diff_det_minus_llm": round(float(recall_diff), 6),
            "valid_paired_positives": effective_positives,
            "valid_paired_negatives": effective_negatives,
        }

    if llm_recall - det_recall > recall_tol:
        return {
            "recommendation": "prefer_llm",
            "reason": "llm_exceeds_recall_tolerance",
            "recall_diff_det_minus_llm": round(float(recall_diff), 6),
            "valid_paired_positives": effective_positives,
            "valid_paired_negatives": effective_negatives,
        }

    return {
        "recommendation": "keep_current_default",
        "reason": "no_clear_advantage",
        "recall_diff_det_minus_llm": round(float(recall_diff), 6),
        "valid_paired_positives": effective_positives,
        "valid_paired_negatives": effective_negatives,
    }


def summarize_paired_eval(
    paired_rows: list[dict[str, Any]],
    ground_truth_by_id: dict[str, dict[str, Any]],
    *,
    min_evaluable_positives: int = 10,
    min_evaluable_negatives: int = 1,
    recall_tolerance: float = 0.05,
    fp_rate_tolerance: float = 0.05,
    max_failure_rate: float = 0.1,
    contract_version: str = "tensile-vlm/v4.1",
) -> dict[str, Any]:
    """Compute paired quality metrics, cost metrics, and planner recommendation.

    Fail-closed on duplicate video IDs or rows missing ground-truth annotations so
    quality and cost statistics always refer to the exact same unique video set.
    """
    seen_ids: set[str] = set()
    duplicates: list[str] = []
    missing_gt: list[str] = []
    for row in paired_rows:
        vid = str(row["video_id"])
        if vid in seen_ids:
            duplicates.append(vid)
        seen_ids.add(vid)
        if vid not in ground_truth_by_id:
            missing_gt.append(vid)

    if duplicates:
        raise ValueError(f"duplicate video_id(s) in paired_rows: {sorted(set(duplicates))}")
    if missing_gt:
        raise ValueError(
            f"video_id(s) missing from ground_truth_by_id: {sorted(set(missing_gt))}"
        )

    det_records: list[tuple[dict[str, Any], dict[str, Any], int]] = []
    llm_records: list[tuple[dict[str, Any], dict[str, Any], int]] = []
    valid_paired_positives = 0
    valid_paired_negatives = 0

    for row in paired_rows:
        vid = str(row["video_id"])
        gt = ground_truth_by_id[vid]
        det_records.append(
            (gt, row["deterministic"]["prediction"], int(row["deterministic"]["visual_calls"]))
        )
        llm_records.append(
            (gt, row["llm"]["prediction"], int(row["llm"]["visual_calls"]))
        )
        both_ok = bool(row["deterministic"].get("ok")) and bool(row["llm"].get("ok"))
        if both_ok and gt.get("special_case") is None:
            if gt.get("has_fracture") is True:
                valid_paired_positives += 1
            elif gt.get("has_fracture") is False:
                valid_paired_negatives += 1

    det_score = score_method(det_records)
    llm_score = score_method(llm_records)
    det_cost = _arm_cost_summary(paired_rows, "deterministic")
    llm_cost = _arm_cost_summary(paired_rows, "llm")
    decision = decide_default_planner(
        det_score,
        llm_score,
        det_cost,
        llm_cost,
        valid_paired_positives=valid_paired_positives,
        valid_paired_negatives=valid_paired_negatives,
        min_evaluable_positives=min_evaluable_positives,
        min_evaluable_negatives=min_evaluable_negatives,
        recall_tolerance=recall_tolerance,
        fp_rate_tolerance=fp_rate_tolerance,
        max_failure_rate=max_failure_rate,
    )

    return {
        "schema_version": PLANNER_PAIRED_EVAL_SCHEMA,
        "contract_version": contract_version,
        "paired_videos": len(paired_rows),
        "scored_videos": len(det_records),
        "valid_paired_positives": valid_paired_positives,
        "valid_paired_negatives": valid_paired_negatives,
        "thresholds": {
            "min_evaluable_positives": min_evaluable_positives,
            "min_evaluable_negatives": min_evaluable_negatives,
            "recall_tolerance": recall_tolerance,
            "fp_rate_tolerance": fp_rate_tolerance,
            "max_failure_rate": max_failure_rate,
        },
        "deterministic": {
            "quality": det_score,
            "negative_fp_rate": _negative_fp_rate(det_score),
            "cost": det_cost,
        },
        "llm": {
            "quality": llm_score,
            "negative_fp_rate": _negative_fp_rate(llm_score),
            "cost": llm_cost,
        },
        "decision": decision,
    }


def _fmt_pct(value: float | None) -> str:
    return f"{value * 100:.2f}%" if isinstance(value, (int, float)) else "N/A"


def render_markdown_report(summary: dict[str, Any]) -> str:
    """Render a concise Markdown comparison table for human review."""
    det = summary["deterministic"]
    llm = summary["llm"]
    det_p = det["quality"]["presence"]
    llm_p = llm["quality"]["presence"]
    det_t = det["quality"]["time"]
    llm_t = llm["quality"]["time"]
    decision = summary["decision"]

    lines = [
        f"# 双规划器同条件配对评测报告（`{summary.get('contract_version', 'tensile-vlm/v4.1')}`）",
        "",
        f"- 协议版本：`{summary['schema_version']}`",
        f"- 配对视频数：`{summary['paired_videos']}`（可评分：`{summary['scored_videos']}`，双臂有效正例：`{summary.get('valid_paired_positives')}`，双臂有效阴性：`{summary.get('valid_paired_negatives')}`）",
        f"- 选型建议：**`{decision['recommendation']}`**（原因：`{decision['reason']}`）",
        "",
        "| 指标 | DeterministicPlanner | LLM Planner |",
        "|---|---|---|",
        f"| 断裂召回率（主指标） | {_fmt_pct(det_p['recall'])} | {_fmt_pct(llm_p['recall'])} |",
        f"| 阴性误报率（FP / (FP+TN)） | {_fmt_pct(det['negative_fp_rate'])} | {_fmt_pct(llm['negative_fp_rate'])} |",
        f"| 拒判率（Abstention） | {_fmt_pct(det_p['abstention_rate'])} | {_fmt_pct(llm_p['abstention_rate'])} |",
        f"| 严格时间窗命中（全正例） | {_fmt_pct(det_t['strict_hit_rate_all_positives'])} | {_fmt_pct(llm_t['strict_hit_rate_all_positives'])} |",
        f"| 执行失败数（单独列示） | {det['cost']['execution_failures']} | {llm['cost']['execution_failures']} |",
        f"| 平均视觉调用次数（分析+证据） | {det['cost']['mean_visual_calls']} | {llm['cost']['mean_visual_calls']} |",
        f"| 平均决策 LLM 调用次数 | {det['cost']['mean_decision_llm_calls']} | {llm['cost']['mean_decision_llm_calls']} |",
        f"| 总采样轮数 | {det['cost']['total_sampling_rounds']} | {llm['cost']['total_sampling_rounds']} |",
        f"| 平均端到端耗时（s） | {det['cost']['mean_elapsed_seconds']} | {llm['cost']['mean_elapsed_seconds']} |",
        "",
    ]
    return "\n".join(lines)
