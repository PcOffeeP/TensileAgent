"""Tests for dual-planner paired evaluation CLI, call_stats, and exact selection rules."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agent.iterative_agent import IterativeAgent
from agent.llm import DeterministicPlanner
from agent.planner_paired_eval import (
    PLANNER_PAIRED_EVAL_SCHEMA,
    render_markdown_report,
    run_paired_video,
    summarize_paired_eval,
)
from agent.schema import UserIntent
from scripts.run_planner_paired_eval import main as cli_main
from tests.test_v4_1_coverage_scheduler import (
    RecordingClipBuilder,
    V41InferenceClient,
    _output,
)


def _gt(
    video_id: str, has_fracture: bool, fracture_time: float | None = None
) -> dict[str, Any]:
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
    det_llm_calls: int = 0,
    llm_llm_calls: int = 5,
    det_elapsed: float = 1.0,
    llm_elapsed: float = 3.0,
) -> dict[str, Any]:
    def _arm(
        status: str,
        time_range: list[float] | None,
        ok: bool,
        decision_llm_calls: int,
        elapsed: float,
    ) -> dict[str, Any]:
        return {
            "ok": ok,
            "error": None
            if ok
            else {"stage": "decision_backend", "code": "timeout", "message": "boom"},
            "prediction": {
                "status": status if ok else "unrecognized",
                "has_fracture": (
                    True
                    if ok and status == "fracture"
                    else False
                    if ok and status == "no_fracture"
                    else None
                ),
                "time_range": time_range if ok and status == "fracture" else None,
                "fracture_type": "韧性断裂" if ok and status == "fracture" else None,
                "location": "inside_gauge" if ok and status == "fracture" else None,
                "special_case": None,
                "unrecognized_reason": None if ok else "execution_failed",
            },
            "visual_analysis_calls": 4,
            "visual_evidence_calls": 0,
            "visual_calls": 4,
            "decision_llm_calls": decision_llm_calls,
            "deterministic_planner_calls": 2 if decision_llm_calls == 0 else 0,
            "program_scheduled_rounds": 1,
            "sampling_rounds": 4,
            "elapsed_seconds": elapsed,
        }

    return {
        "schema_version": PLANNER_PAIRED_EVAL_SCHEMA,
        "video_id": video_id,
        "question": "请完整分析这段拉伸试验视频",
        "deterministic": _arm(det_status, det_time, det_ok, det_llm_calls, det_elapsed),
        "llm": _arm(llm_status, llm_time, llm_ok, llm_llm_calls, llm_elapsed),
    }


def test_cli_help_runs_without_import_error() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.run_planner_paired_eval", "--help"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--annotations" in proc.stdout
    assert "--llm-model" in proc.stdout


def test_run_paired_video_shares_resolved_intent_and_reads_real_call_stats(
    tmp_path: Path,
) -> None:
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
                    "history": [{}] * 6,
                    "call_stats": {
                        "visual_analysis_calls": 6,
                        "visual_evidence_calls": 0,
                        "decision_llm_calls": 0,
                        "deterministic_planner_calls": 1,
                        "program_scheduled_rounds": 5,
                    },
                },
            }
        return {
            "ok": False,
            "error": {
                "stage": "decision_backend",
                "code": "LocalModelMissing",
                "message": "not installed",
            },
            "evaluation_trace": {
                "rounds": 1,
                "history": [{}],
                "call_stats": {
                    "visual_analysis_calls": 0,
                    "visual_evidence_calls": 0,
                    "decision_llm_calls": 1,
                    "deterministic_planner_calls": 0,
                    "program_scheduled_rounds": 0,
                },
            },
        }

    fixed_intent = UserIntent(
        requested_fields=["has_fracture", "time_range"],
        wants_evidence=False,
        wants_confidence=False,
    )
    row = run_paired_video(
        video_id="video_0001",
        video_path=tmp_path / "video_0001.mp4",
        config_path="agent/config.yaml",
        work_dir=tmp_path / "work",
        resolved_intent=fixed_intent,
        llm_backend="local",
        llm_model="qwen3:8b",
        runner_fn=fake_runner,
    )

    assert len(calls) == 2
    assert calls[0]["resolved_intent"] == fixed_intent
    assert calls[1]["resolved_intent"] == fixed_intent
    assert row["deterministic"]["decision_llm_calls"] == 0
    assert row["deterministic"]["deterministic_planner_calls"] == 1
    assert row["deterministic"]["visual_analysis_calls"] == 6
    assert row["llm"]["ok"] is False
    assert row["llm"]["decision_llm_calls"] == 1
    assert row["llm"]["visual_analysis_calls"] == 0


def test_iterative_agent_call_stats_tracks_real_boundaries_not_sampling_failures() -> None:
    class FailingClipBuilder:
        def build_with_manifest(self, source_video: str, sample_range: list[float]) -> Any:
            del source_video, sample_range
            raise RuntimeError("ffmpeg boom")

    agent = IterativeAgent(
        llm_client=DeterministicPlanner(model="v4.1-interval-policy-v1"),
        video_meta={"video_id": "v_clip_fail", "duration": 40.0, "video_path": "v.mp4"},
        config={
            "agent": {"max_rounds": 3, "tolerance_seconds": 1.0, "temperature": 0.2},
            "backend": {"contract_version": "tensile-vlm/v4.1"},
        },
        clip_builder=FailingClipBuilder(),  # type: ignore[arg-type]
        inference_client=V41InferenceClient([_output("未断裂")]),
    )
    result = agent.run()
    assert result["ok"] is False
    assert agent.call_stats["visual_analysis_calls"] == 0
    assert agent.call_stats["decision_llm_calls"] == 0
    assert agent.call_stats["deterministic_planner_calls"] == 2
    assert len(agent.history) == 2

    # Normal global negative: 1 deterministic planner call, 6 visual calls, 5 program-scheduled rounds.
    agent_ok = IterativeAgent(
        llm_client=DeterministicPlanner(model="v4.1-interval-policy-v1"),
        video_meta={"video_id": "v_ok", "duration": 40.0, "video_path": "v.mp4"},
        config={
            "agent": {"max_rounds": 6, "tolerance_seconds": 1.0, "temperature": 0.2},
            "backend": {"contract_version": "tensile-vlm/v4.1"},
        },
        clip_builder=RecordingClipBuilder(),
        inference_client=V41InferenceClient([_output("未断裂") for _ in range(6)]),
    )
    res_ok = agent_ok.run()
    assert res_ok["status"] == "no_fracture"
    assert agent_ok.call_stats == {
        "visual_analysis_calls": 6,
        "visual_evidence_calls": 0,
        "decision_llm_calls": 0,
        "deterministic_planner_calls": 1,
        "program_scheduled_rounds": 5,
    }


def test_cli_rejects_duplicate_ids_missing_annotations_and_non_v4_1_config(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "ann.csv"
    csv_path.write_text(
        "video_id,has_fracture,source_type\nv1,true,韧性断裂\nv2,false,未断裂\n",
        encoding="utf-8",
    )
    v41_cfg = tmp_path / "v41.yaml"
    v41_cfg.write_text(
        "agent:\n  backend: local\nbackend:\n  contract_version: tensile-vlm/v4.1\n",
        encoding="utf-8",
    )
    v2_cfg = tmp_path / "v2.yaml"
    v2_cfg.write_text(
        "agent:\n  backend: local\nbackend:\n  contract_version: tensile-vlm/v2\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"

    with pytest.raises(ValueError, match="duplicate video_id"):
        cli_main(
            [
                "--videos-root",
                str(tmp_path),
                "--annotations",
                str(csv_path),
                "--config",
                str(v41_cfg),
                "--output-dir",
                str(out_dir),
                "--video-ids",
                "v1",
                "v1",
            ]
        )
    assert not out_dir.exists()

    with pytest.raises(ValueError, match="missing from annotations"):
        cli_main(
            [
                "--videos-root",
                str(tmp_path),
                "--annotations",
                str(csv_path),
                "--config",
                str(v41_cfg),
                "--output-dir",
                str(out_dir),
                "--video-ids",
                "v1",
                "unknown_vid",
            ]
        )
    assert not out_dir.exists()

    with pytest.raises(ValueError, match="tensile-vlm/v4.1"):
        cli_main(
            [
                "--videos-root",
                str(tmp_path),
                "--annotations",
                str(csv_path),
                "--config",
                str(v2_cfg),
                "--output-dir",
                str(out_dir),
                "--video-ids",
                "v1",
            ]
        )
    assert not out_dir.exists()


def test_cli_end_to_end_smoke_writes_ledger_summary_and_report(tmp_path: Path) -> None:
    csv_path = tmp_path / "ann.csv"
    csv_path.write_text(
        "video_id,has_fracture,source_type\nv1,true,韧性断裂\nv2,false,未断裂\n",
        encoding="utf-8",
    )
    v41_cfg = tmp_path / "v41.yaml"
    v41_cfg.write_text(
        "agent:\n  backend: local\nbackend:\n  contract_version: tensile-vlm/v4.1\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"

    def stub_runner(**kwargs: Any) -> dict[str, Any]:
        is_pos = kwargs["video_id"] == "v1"
        return {
            "ok": True,
            "result": {
                "status": "fracture" if is_pos else "no_fracture",
                "has_fracture": is_pos,
                "time_range": [10.0, 10.5] if is_pos else None,
                "fracture_type": "韧性断裂" if is_pos else None,
                "location": "inside_gauge" if is_pos else None,
                "special_case": None,
                "unrecognized_reason": None,
            },
            "evaluation_trace": {
                "rounds": 2,
                "history": [{}, {}],
                "call_stats": {
                    "visual_analysis_calls": 2,
                    "visual_evidence_calls": 0,
                    "decision_llm_calls": 0 if kwargs["agent_backend"] == "deterministic" else 2,
                    "deterministic_planner_calls": 2 if kwargs["agent_backend"] == "deterministic" else 0,
                    "program_scheduled_rounds": 0,
                },
            },
        }

    summary = cli_main(
        [
            "--videos-root",
            str(tmp_path),
            "--annotations",
            str(csv_path),
            "--config",
            str(v41_cfg),
            "--output-dir",
            str(out_dir),
            "--video-ids",
            "v1",
            "v2",
        ],
        runner_fn=stub_runner,
    )
    assert summary["paired_videos"] == 2
    assert (out_dir / "paired_ledger.jsonl").is_file()
    assert (out_dir / "summary.json").is_file()
    assert (out_dir / "REPORT.md").is_file()
    loaded = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
    assert loaded["contract_version"] == "tensile-vlm/v4.1"


def test_summarize_rejects_duplicate_rows_and_missing_gt() -> None:
    gt = {"p0": _gt("p0", True, 12.0)}
    dup_rows = [
        _paired_row("p0", det_status="fracture", llm_status="fracture"),
        _paired_row("p0", det_status="fracture", llm_status="fracture"),
    ]
    with pytest.raises(ValueError, match="duplicate video_id"):
        summarize_paired_eval(dup_rows, gt)

    missing_rows = [_paired_row("missing", det_status="fracture", llm_status="fracture")]
    with pytest.raises(ValueError, match="missing from ground_truth_by_id"):
        summarize_paired_eval(missing_rows, gt)


def test_summarize_exact_fraction_boundary_19_of_20_prefers_deterministic() -> None:
    """19/20 vs 20/20 is exactly -0.05; float rounding must not flip to prefer_llm."""
    gt = {
        **{f"p{i}": _gt(f"p{i}", True, 12.0) for i in range(20)},
        **{f"n{i}": _gt(f"n{i}", False) for i in range(5)},
    }
    rows = [
        *[
            _paired_row(
                f"p{i}",
                det_status="fracture" if i < 19 else "no_fracture",
                llm_status="fracture",
                det_time=[11.5, 12.5],
                llm_time=[11.5, 12.5],
            )
            for i in range(20)
        ],
        *[
            _paired_row(f"n{i}", det_status="no_fracture", llm_status="no_fracture")
            for i in range(5)
        ],
    ]

    summary = summarize_paired_eval(
        rows,
        gt,
        min_evaluable_positives=10,
        min_evaluable_negatives=1,
        recall_tolerance=0.05,
    )
    assert summary["decision"]["recommendation"] == "prefer_deterministic"
    report = render_markdown_report(summary)
    assert "prefer_deterministic" in report


def test_summarize_does_not_reward_faster_execution_failures_or_missing_negatives() -> None:
    gt_pos_only = {f"p{i}": _gt(f"p{i}", True, 12.0) for i in range(10)}
    all_failed_rows = [
        _paired_row(
            f"p{i}",
            det_status="unrecognized",
            llm_status="unrecognized",
            det_ok=False,
            llm_ok=False,
            det_elapsed=0.1,
            llm_elapsed=5.0,
        )
        for i in range(10)
    ]
    failed_summary = summarize_paired_eval(all_failed_rows, gt_pos_only)
    assert failed_summary["decision"]["recommendation"] == "keep_current_default"
    assert failed_summary["decision"]["reason"] == "excessive_execution_failures"

    # Even when all positives succeed, missing negative samples must not silently pass FP gate.
    pos_only_ok_rows = [
        _paired_row(f"p{i}", det_status="fracture", llm_status="fracture")
        for i in range(10)
    ]
    no_neg_summary = summarize_paired_eval(pos_only_ok_rows, gt_pos_only)
    assert no_neg_summary["decision"]["recommendation"] == "keep_current_default"
    assert no_neg_summary["decision"]["reason"] == "insufficient_negative_samples"


def test_summarize_prefers_llm_when_recall_advantage_exceeds_tolerance() -> None:
    gt = {
        **{f"p{i}": _gt(f"p{i}", True, 12.0) for i in range(10)},
        **{f"n{i}": _gt(f"n{i}", False) for i in range(3)},
    }
    rows = [
        *[
            _paired_row(f"p{i}", det_status="fracture", llm_status="fracture")
            for i in range(6)
        ],
        *[
            _paired_row(f"p{i}", det_status="no_fracture", llm_status="fracture")
            for i in range(6, 10)
        ],
        *[
            _paired_row(f"n{i}", det_status="no_fracture", llm_status="no_fracture")
            for i in range(3)
        ],
    ]

    summary = summarize_paired_eval(
        rows, gt, min_evaluable_positives=10, recall_tolerance=0.05
    )
    assert summary["decision"]["recommendation"] == "prefer_llm"
    assert summary["decision"]["reason"] == "llm_exceeds_recall_tolerance"


def test_common_negative_fp_rate_prevents_single_arm_failure_reversing_verdict() -> None:
    """Exact Codex scenario: 10 pos both TP, 9 common neg (det 1 FP, llm 0 FP), 10th neg det fails & llm FP."""
    gt = {
        **{f"p{i}": _gt(f"p{i}", True, 12.0) for i in range(10)},
        **{f"n{i}": _gt(f"n{i}", False) for i in range(10)},
    }
    rows = [
        *[
            _paired_row(
                f"p{i}",
                det_status="fracture",
                llm_status="fracture",
                det_time=[11.5, 12.5],
                llm_time=[11.5, 12.5],
            )
            for i in range(10)
        ],
        _paired_row("n0", det_status="fracture", llm_status="no_fracture"),
        *[
            _paired_row(f"n{i}", det_status="no_fracture", llm_status="no_fracture")
            for i in range(1, 9)
        ],
        _paired_row(
            "n9",
            det_status="unrecognized",
            llm_status="fracture",
            det_ok=False,
            llm_ok=True,
        ),
    ]

    summary = summarize_paired_eval(
        rows,
        gt,
        min_evaluable_positives=10,
        min_evaluable_negatives=1,
        fp_rate_tolerance=0.05,
        max_failure_rate=0.1,
    )
    assert summary["common_decided_negatives"] == 9
    assert summary["deterministic"]["common_negative_fp_rate"] == pytest.approx(1 / 9)
    assert summary["llm"]["common_negative_fp_rate"] == 0.0
    # On the 9 common negatives, det FP diff is 1/9 (> 0.05), so it must NOT prefer deterministic.
    assert summary["decision"]["recommendation"] == "keep_current_default"


def test_visual_deployment_mismatch_blocks_preference_recommendation() -> None:
    gt = {
        **{f"p{i}": _gt(f"p{i}", True, 12.0) for i in range(10)},
        "n0": _gt("n0", False),
    }
    rows = [
        *[
            _paired_row(f"p{i}", det_status="fracture", llm_status="fracture")
            for i in range(10)
        ],
        _paired_row("n0", det_status="no_fracture", llm_status="no_fracture"),
    ]
    rows[0]["deployment_matched"] = False
    rows[0]["deterministic"]["visual_deployment"] = {"adapter_version": "a1"}
    rows[0]["llm"]["visual_deployment"] = {"adapter_version": "a2"}

    summary = summarize_paired_eval(rows, gt)
    assert summary["deployment_mismatch_count"] == 1
    assert summary["decision"]["recommendation"] == "keep_current_default"
    assert summary["decision"]["reason"] == "visual_deployment_mismatch"


def test_runner_outer_exception_preserves_agent_call_stats(tmp_path: Path) -> None:
    """Real run_one outer exception (e.g. TypeError on JSON array tool args) keeps decision_llm_calls."""
    from unittest.mock import MagicMock, patch
    from agent import runner
    from agent.llm import BaseAgentLLM

    class ArrayArgsLLM(BaseAgentLLM):
        def chat_with_tools(self, messages, tools, temperature=0.2, max_tokens=None):
            del messages, tools, temperature, max_tokens
            tc = MagicMock()
            tc.id = "bad-1"
            tc.type = "function"
            tc.function.name = "sample_and_infer"
            tc.function.arguments = "[]"
            msg = MagicMock(content="", tool_calls=[tc])
            return MagicMock(choices=[MagicMock(message=msg)])

        @property
        def model_name(self) -> str:
            return "test/array-args"

    video = tmp_path / "demo.mp4"
    video.write_bytes(b"fake")
    cfg = tmp_path / "v41.yaml"
    cfg.write_text(
        "agent:\n  backend: local\n  tolerance_seconds: 1.0\nbackend:\n  contract_version: tensile-vlm/v4.1\n",
        encoding="utf-8",
    )

    with (
        patch("agent.runner.build_video_meta", return_value={"video_id": "demo", "duration": 40.0, "video_path": str(video)}),
        patch("agent.runner.create_llm_client", return_value=ArrayArgsLLM()),
        patch("agent.runner.create_inference_client") as mock_inf,
        patch("agent.runner.create_clip_builder", return_value=RecordingClipBuilder()),
    ):
        mock_inf.return_value = V41InferenceClient([_output("未断裂")])
        mock_inf.return_value.preflight = lambda: V41InferenceClient.deployment_snapshot
        env = runner.run_one(
            video,
            config_path=cfg,
            resolved_intent=UserIntent(requested_fields=["has_fracture"]),
            include_internal_trace=True,
        )

    assert env["ok"] is False
    assert env["evaluation_trace"]["call_stats"]["decision_llm_calls"] == 1


def test_cli_rejects_nan_threshold_and_refuses_overwrite_without_flag(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "ann.csv"
    csv_path.write_text("video_id,has_fracture,source_type\nv1,true,韧性断裂\n", encoding="utf-8")
    v41_cfg = tmp_path / "v41.yaml"
    v41_cfg.write_text(
        "agent:\n  backend: local\nbackend:\n  contract_version: tensile-vlm/v4.1\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    existing_ledger = out_dir / "paired_ledger.jsonl"
    existing_ledger.write_text("old-run\n", encoding="utf-8")

    with pytest.raises(ValueError, match="--max-failure-rate"):
        cli_main(
            [
                "--videos-root",
                str(tmp_path),
                "--annotations",
                str(csv_path),
                "--config",
                str(v41_cfg),
                "--output-dir",
                str(out_dir),
                "--max-failure-rate",
                "nan",
            ]
        )
    assert existing_ledger.read_text(encoding="utf-8") == "old-run\n"

    with pytest.raises(FileExistsError, match="--overwrite"):
        cli_main(
            [
                "--videos-root",
                str(tmp_path),
                "--annotations",
                str(csv_path),
                "--config",
                str(v41_cfg),
                "--output-dir",
                str(out_dir),
            ]
        )
    assert existing_ledger.read_text(encoding="utf-8") == "old-run\n"
