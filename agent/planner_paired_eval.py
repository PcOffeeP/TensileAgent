"""Paired evaluation utilities comparing DeterministicPlanner vs LLM planner on the same V4.1 Runtime."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from agent.runner import run_one
from agent.strategy_ab_scoring import score_method

PLANNER_PAIRED_EVAL_SCHEMA = "tensile-agent/planner-paired-eval/v1"


def _extract_arm_metrics(
    runner_result: dict[str, Any],
    *,
    elapsed_seconds: float,
) -> dict[str, Any]:
    """Extract standardized prediction, call counts, and failure info from one run_one envelope."""
    ok = runner_result.get("ok") is True
    trace = runner_result.get("evaluation_trace") or {}
    history = trace.get("history") or []
    visual_calls = len(history)
    program_calls = sum(
        1 for entry in history if entry.get("model") == "program/scheduler"
    )
    decision_calls = max(0, visual_calls - program_calls)

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
            "visual_calls": visual_calls,
            "program_scheduled_calls": program_calls,
            "decision_calls": decision_calls,
            "elapsed_seconds": round(float(elapsed_seconds), 4),
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
        "visual_calls": visual_calls,
        "program_scheduled_calls": program_calls,
        "decision_calls": decision_calls,
        "elapsed_seconds": round(float(elapsed_seconds), 4),
    }


def run_paired_video(
    *,
    video_id: str,
    video_path: str | Path,
    config_path: str | Path,
    work_dir: str | Path,
    question: str = "请完整分析这段拉伸试验视频",
    llm_backend: str = "local",
    llm_model: str | None = None,
    deterministic_model: str = "v4.1-interval-policy-v1",
    runner_fn: Callable[..., dict[str, Any]] = run_one,
) -> dict[str, Any]:
    """Run deterministic and LLM planners on the exact same video and runtime settings."""
    work_root = Path(work_dir)

    t0 = time.monotonic()
    det_raw = runner_fn(
        video_path=video_path,
        config_path=config_path,
        video_id=video_id,
        work_dir=work_root / "deterministic" / video_id,
        agent_backend="deterministic",
        agent_model=deterministic_model,
        question=question,
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
        trace_task_id=f"paired-llm-{video_id}",
        include_internal_trace=True,
    )
    llm_elapsed = time.monotonic() - t1

    return {
        "schema_version": PLANNER_PAIRED_EVAL_SCHEMA,
        "video_id": video_id,
        "question": question,
        "deterministic": _extract_arm_metrics(det_raw, elapsed_seconds=det_elapsed),
        "llm": _extract_arm_metrics(llm_raw, elapsed_seconds=llm_elapsed),
    }


def _arm_cost_summary(rows: list[dict[str, Any]], arm: str) -> dict[str, Any]:
    arm_rows = [row[arm] for row in rows]
    n = len(arm_rows)
    failures = sum(1 for item in arm_rows if not item.get("ok"))
    visual_total = sum(int(item.get("visual_calls", 0)) for item in arm_rows)
    decision_total = sum(int(item.get("decision_calls", 0)) for item in arm_rows)
    elapsed_total = sum(float(item.get("elapsed_seconds", 0.0)) for item in arm_rows)
    return {
        "videos": n,
        "execution_failures": failures,
        "total_visual_calls": visual_total,
        "mean_visual_calls": round(visual_total / n, 3) if n else None,
        "total_decision_calls": decision_total,
        "mean_decision_calls": round(decision_total / n, 3) if n else None,
        "total_elapsed_seconds": round(elapsed_total, 4),
        "mean_elapsed_seconds": round(elapsed_total / n, 4) if n else None,
    }


def _negative_fp_rate(score: dict[str, Any]) -> float | None:
    confusion = (score.get("presence") or {}).get("confusion") or {}
    fp = int(confusion.get("fp", 0))
    tn = int(confusion.get("tn", 0))
    return fp / (fp + tn) if (fp + tn) > 0 else None


def decide_default_planner(
    det_score: dict[str, Any],
    llm_score: dict[str, Any],
    det_cost: dict[str, Any],
    llm_cost: dict[str, Any],
    *,
    min_evaluable_positives: int = 10,
    recall_tolerance: float = 0.05,
    fp_rate_tolerance: float = 0.05,
) -> dict[str, Any]:
    """Apply pre-agreed quality and cost thresholds to recommend a default planner."""
    det_conf = (det_score.get("presence") or {}).get("confusion") or {}
    evaluable_positives = int(det_conf.get("tp", 0)) + int(det_conf.get("fn", 0))
    det_recall = (det_score.get("presence") or {}).get("recall")
    llm_recall = (llm_score.get("presence") or {}).get("recall")
    det_fp = _negative_fp_rate(det_score)
    llm_fp = _negative_fp_rate(llm_score)

    if (
        evaluable_positives < min_evaluable_positives
        or det_recall is None
        or llm_recall is None
    ):
        return {
            "recommendation": "keep_current_default",
            "reason": "insufficient_sample_size",
            "evaluable_positives": evaluable_positives,
            "min_evaluable_positives": min_evaluable_positives,
        }

    recall_diff = det_recall - llm_recall
    fp_within_tolerance = (
        True
        if det_fp is None or llm_fp is None
        else det_fp <= llm_fp + fp_rate_tolerance
    )
    det_cheaper = (
        (det_cost.get("total_decision_calls") or 0)
        < (llm_cost.get("total_decision_calls") or 0)
        or (det_cost.get("total_elapsed_seconds") or 0.0)
        < (llm_cost.get("total_elapsed_seconds") or 0.0)
    )

    if recall_diff >= -recall_tolerance and fp_within_tolerance and det_cheaper:
        return {
            "recommendation": "prefer_deterministic",
            "reason": "within_quality_tolerance_and_lower_cost",
            "recall_diff_det_minus_llm": round(recall_diff, 4),
            "evaluable_positives": evaluable_positives,
        }

    if llm_recall - det_recall > recall_tolerance:
        return {
            "recommendation": "prefer_llm",
            "reason": "llm_exceeds_recall_tolerance",
            "recall_diff_det_minus_llm": round(recall_diff, 4),
            "evaluable_positives": evaluable_positives,
        }

    return {
        "recommendation": "keep_current_default",
        "reason": "no_clear_advantage",
        "recall_diff_det_minus_llm": round(recall_diff, 4),
        "evaluable_positives": evaluable_positives,
    }


def summarize_paired_eval(
    paired_rows: list[dict[str, Any]],
    ground_truth_by_id: dict[str, dict[str, Any]],
    *,
    min_evaluable_positives: int = 10,
    recall_tolerance: float = 0.05,
    fp_rate_tolerance: float = 0.05,
) -> dict[str, Any]:
    """Compute paired quality metrics, cost metrics, and planner recommendation."""
    det_records: list[tuple[dict[str, Any], dict[str, Any], int]] = []
    llm_records: list[tuple[dict[str, Any], dict[str, Any], int]] = []
    missing_gt: list[str] = []

    for row in paired_rows:
        vid = str(row["video_id"])
        gt = ground_truth_by_id.get(vid)
        if gt is None:
            missing_gt.append(vid)
            continue
        det_records.append(
            (gt, row["deterministic"]["prediction"], int(row["deterministic"]["visual_calls"]))
        )
        llm_records.append(
            (gt, row["llm"]["prediction"], int(row["llm"]["visual_calls"]))
        )

    det_score = score_method(det_records)
    llm_score = score_method(llm_records)
    det_cost = _arm_cost_summary(paired_rows, "deterministic")
    llm_cost = _arm_cost_summary(paired_rows, "llm")
    decision = decide_default_planner(
        det_score,
        llm_score,
        det_cost,
        llm_cost,
        min_evaluable_positives=min_evaluable_positives,
        recall_tolerance=recall_tolerance,
        fp_rate_tolerance=fp_rate_tolerance,
    )

    return {
        "schema_version": PLANNER_PAIRED_EVAL_SCHEMA,
        "paired_videos": len(paired_rows),
        "scored_videos": len(det_records),
        "missing_ground_truth_ids": missing_gt,
        "thresholds": {
            "min_evaluable_positives": min_evaluable_positives,
            "recall_tolerance": recall_tolerance,
            "fp_rate_tolerance": fp_rate_tolerance,
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
        "# V4.1 双规划器同条件配对评测报告",
        "",
        f"- 协议版本：`{summary['schema_version']}`",
        f"- 配对视频数：`{summary['paired_videos']}`（可评分：`{summary['scored_videos']}`）",
        f"- 选型建议：**`{decision['recommendation']}`**（原因：`{decision['reason']}`）",
        "",
        "| 指标 | DeterministicPlanner | LLM Planner |",
        "|---|---|---|",
        f"| 断裂召回率（主指标） | {_fmt_pct(det_p['recall'])} | {_fmt_pct(llm_p['recall'])} |",
        f"| 阴性误报率（FP / (FP+TN)） | {_fmt_pct(det['negative_fp_rate'])} | {_fmt_pct(llm['negative_fp_rate'])} |",
        f"| 拒判率（Abstention） | {_fmt_pct(det_p['abstention_rate'])} | {_fmt_pct(llm_p['abstention_rate'])} |",
        f"| 严格时间窗命中（全正例） | {_fmt_pct(det_t['strict_hit_rate_all_positives'])} | {_fmt_pct(llm_t['strict_hit_rate_all_positives'])} |",
        f"| 执行失败数（单独列示） | {det['cost']['execution_failures']} | {llm['cost']['execution_failures']} |",
        f"| 平均视觉调用次数 | {det['cost']['mean_visual_calls']} | {llm['cost']['mean_visual_calls']} |",
        f"| 平均决策模型调用次数 | {det['cost']['mean_decision_calls']} | {llm['cost']['mean_decision_calls']} |",
        f"| 平均端到端耗时（s） | {det['cost']['mean_elapsed_seconds']} | {llm['cost']['mean_elapsed_seconds']} |",
        "",
    ]
    return "\n".join(lines)
