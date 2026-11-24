"""Tests for dual-planner paired evaluation utilities and selection rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.planner_paired_eval import (
    PLANNER_PAIRED_EVAL_SCHEMA,
    render_markdown_report,
    run_paired_video,
    summarize_paired_eval,
)


def _gt(video_id: str, has_fracture: bool, fracture_time: float | None = None) -> dict[str, Any]:
    return {
        "video_id": video_id,
        "has_fracture": has_fracture,
        "fracture_mechanism": "韧性断裂" if has_fracture else None,
        "fracture_site": "inside_gauge" if has_fracture else None,
        "special_case": None,
        "fracture_time": fracture_time,
        "duration": 40.0,
    }


def _paired_row(
    video_id: str,
    *,
    det_status: str,
    llm_status: str,
    det_time: list[float] | None = None,
    llm_time: list[float] | None = None,
    det_ok: bool = True,
    llm_ok: bool = True,
    det_dec_calls: int = 2,
    llm_dec_calls: int = 5,
) -> dict[str, Any]:
    def _arm(status: str, time_range: list[float] | None, ok: bool, dec_calls: int) -> dict[str, Any]:
        return {
            "ok": ok,
            "error": None if ok else {"stage": "decision_backend", "code": "timeout", "message": "boom"},
            "prediction": {
                "status": status if ok else "unrecognized",
                "has_fracture": (
                    True if ok and status == "fracture" else False if ok and status == "no_fracture" else None
                ),
                "time_range": time_range if ok and status == "fracture" else None,
                "fracture_type": "韧性断裂" if ok and status == "fracture" else None,
                "location": "inside_gauge" if ok and status == "fracture" else None,
                "special_case": None,
                "unrecognized_reason": None if ok else "execution_failed",
            },
            "visual_calls": dec_calls + 1,
            "program_scheduled_calls": 1,
            "decision_calls": dec_calls,
            "elapsed_seconds": float(dec_calls) * 0.5,
        }

    return {
        "schema_version": PLANNER_PAIRED_EVAL_SCHEMA,
        "video_id": video_id,
        "question": "请完整分析这段拉伸试验视频",
        "deterministic": _arm(det_status, det_time, det_ok, det_dec_calls),
        "llm": _arm(llm_status, llm_time, llm_ok, llm_dec_calls),
    }


def test_run_paired_video_executes_both_arms_and_retains_failures(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def fake_runner(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        if kwargs["agent_backend"] == "deterministic":
            return {
                "ok": True,
                "result": {
                    "status": "no_fracture",
                    "has_fracture": False,
                    "time_range": None,
                    "fracture_type": None,
                    "location": None,
                    "special_case": None,
                    "unrecognized_reason": None,
                },
                "evaluation_trace": {
                    "rounds": 6,
                    "history": [
                        {"model": "deterministic/v4.1-interval-policy-v1"},
                        *[{"model": "program/scheduler"} for _ in range(5)],
                    ],
                },
            }
        return {
            "ok": False,
            "error": {"stage": "decision_backend", "code": "LocalModelMissing", "message": "not installed"},
        }

    row = run_paired_video(
        video_id="video_0001",
        video_path=tmp_path / "video_0001.mp4",
        config_path="agent/config.yaml",
        work_dir=tmp_path / "work",
        llm_backend="local",
        llm_model="qwen3:8b",
        runner_fn=fake_runner,
    )

    assert len(calls) == 2
    assert calls[0]["agent_backend"] == "deterministic"
    assert calls[1]["agent_backend"] == "local"
    assert calls[1]["agent_model"] == "qwen3:8b"
    assert calls[0]["question"] == calls[1]["question"]
    assert row["deterministic"]["ok"] is True
    assert row["deterministic"]["visual_calls"] == 6
    assert row["deterministic"]["program_scheduled_calls"] == 5
    assert row["deterministic"]["decision_calls"] == 1
    assert row["llm"]["ok"] is False
    assert row["llm"]["prediction"]["unrecognized_reason"] == "execution_failed"


def test_summarize_prefers_deterministic_when_within_tolerance_and_cheaper() -> None:
    gt = {
        **{f"p{i}": _gt(f"p{i}", True, 12.0) for i in range(10)},
        **{f"n{i}": _gt(f"n{i}", False) for i in range(5)},
    }
    rows = [
        *[
            _paired_row(
                f"p{i}",
                det_status="fracture",
                llm_status="fracture",
                det_time=[11.5, 12.5],
                llm_time=[11.5, 12.5],
                det_dec_calls=2,
                llm_dec_calls=5,
            )
            for i in range(10)
        ],
        *[
            _paired_row(
                f"n{i}",
                det_status="no_fracture",
                llm_status="no_fracture",
                det_dec_calls=1,
                llm_dec_calls=1,
            )
            for i in range(5)
        ],
    ]

    summary = summarize_paired_eval(rows, gt, min_evaluable_positives=10)
    assert summary["decision"]["recommendation"] == "prefer_deterministic"
    report = render_markdown_report(summary)
    assert "prefer_deterministic" in report
    assert "断裂召回率" in report


def test_summarize_prefers_llm_when_recall_advantage_exceeds_tolerance() -> None:
    gt = {f"p{i}": _gt(f"p{i}", True, 12.0) for i in range(10)}
    rows = [
        *[
            _paired_row(f"p{i}", det_status="fracture", llm_status="fracture")
            for i in range(6)
        ],
        *[
            _paired_row(f"p{i}", det_status="no_fracture", llm_status="fracture")
            for i in range(6, 10)
        ],
    ]

    summary = summarize_paired_eval(rows, gt, min_evaluable_positives=10, recall_tolerance=0.05)
    assert summary["decision"]["recommendation"] == "prefer_llm"
    assert summary["decision"]["reason"] == "llm_exceeds_recall_tolerance"


def test_summarize_keeps_default_when_sample_size_is_insufficient() -> None:
    gt = {"p0": _gt("p0", True, 12.0), "n0": _gt("n0", False)}
    rows = [
        _paired_row("p0", det_status="fracture", llm_status="fracture"),
        _paired_row("n0", det_status="no_fracture", llm_status="no_fracture", llm_ok=False),
    ]

    summary = summarize_paired_eval(rows, gt, min_evaluable_positives=10)
    assert summary["decision"]["recommendation"] == "keep_current_default"
    assert summary["decision"]["reason"] == "insufficient_sample_size"
    assert summary["llm"]["cost"]["execution_failures"] == 1
