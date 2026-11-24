#!/usr/bin/env python3
"""Run paired evaluation comparing DeterministicPlanner vs LLM planner on the same V4.1 Runtime."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from agent.contract import V4_1_CONTRACT_VERSION
from agent.planner_paired_eval import (
    render_markdown_report,
    resolve_shared_intent,
    run_paired_video,
    summarize_paired_eval,
)
from agent.runner import load_config, run_one
from agent.scoring_v4_1 import load_annotation_rows, normalize_ground_truth
from agent.strategy_ab import DIAGNOSTIC_30_IDS


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Paired evaluation of DeterministicPlanner vs LLM planner under identical "
            "V4.1 Runtime constraints. Pass --llm-model explicitly if agent.local.model is blank."
        )
    )
    parser.add_argument("--videos-root", type=Path, required=True, help="Directory containing <video_id>.mp4 files.")
    parser.add_argument("--annotations", type=Path, required=True, help="Ground-truth annotations CSV file.")
    parser.add_argument("--config", type=Path, default=Path("agent/config.yaml"), help="Base V4.1 config YAML.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory to write ledger, summary, and report.")
    parser.add_argument(
        "--video-ids",
        nargs="*",
        default=None,
        help="Optional unique subset of annotated video IDs; defaults to diagnostic30 intersection with annotations.",
    )
    parser.add_argument("--llm-backend", choices=("local", "remote"), default="local")
    parser.add_argument("--llm-model", default=None, help="Explicit LLM planner model name (recommended when config default is blank).")
    parser.add_argument("--question", default="请完整分析这段拉伸试验视频")
    parser.add_argument("--min-evaluable-positives", type=int, default=10)
    parser.add_argument("--min-evaluable-negatives", type=int, default=1)
    parser.add_argument("--recall-tolerance", type=float, default=0.05)
    parser.add_argument("--fp-rate-tolerance", type=float, default=0.05)
    parser.add_argument("--max-failure-rate", type=float, default=0.1)
    parser.add_argument("--mock", action="store_true", help="Enable INFERENCE_MOCK=1 for offline smoke runs.")
    return parser.parse_args(argv)


def _resolve_target_ids(
    requested_ids: list[str] | None,
    annotations: dict[str, dict[str, Any]],
) -> list[str]:
    """Validate target video IDs fail-closed before running either planner arm."""
    if requested_ids is not None:
        if not requested_ids:
            raise ValueError("--video-ids must not be empty when provided")
        duplicates = sorted(
            vid for vid, count in Counter(requested_ids).items() if count > 1
        )
        if duplicates:
            raise ValueError(f"duplicate video_id(s) in --video-ids: {duplicates}")
        missing = sorted(vid for vid in requested_ids if vid not in annotations)
        if missing:
            raise ValueError(
                f"video_id(s) in --video-ids missing from annotations: {missing}"
            )
        return list(requested_ids)

    target_ids = [vid for vid in DIAGNOSTIC_30_IDS if vid in annotations]
    if not target_ids:
        target_ids = sorted(annotations.keys())
    if not target_ids:
        raise ValueError("no annotated video IDs available to evaluate")
    return target_ids


def main(
    argv: list[str] | None = None,
    *,
    runner_fn: Callable[..., dict[str, Any]] = run_one,
) -> dict[str, Any]:
    args = _parse_args(argv)
    if args.mock:
        os.environ["INFERENCE_MOCK"] = "1"

    config = load_config(args.config)
    contract_version = str(
        (config.get("backend") or {}).get("contract_version") or ""
    )
    if contract_version != V4_1_CONTRACT_VERSION:
        raise ValueError(
            f"paired evaluation requires {V4_1_CONTRACT_VERSION} config, got {contract_version!r}"
        )

    raw_annotations = load_annotation_rows(args.annotations)
    annotations = {
        vid: normalize_ground_truth(row) for vid, row in raw_annotations.items()
    }
    target_ids = _resolve_target_ids(args.video_ids, annotations)
    shared_intent = resolve_shared_intent(args.question)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = args.output_dir / "paired_ledger.jsonl"
    rows: list[dict[str, Any]] = []

    with ledger_path.open("w", encoding="utf-8") as handle:
        for video_id in target_ids:
            video_path = args.videos_root / f"{video_id}.mp4"
            row = run_paired_video(
                video_id=video_id,
                video_path=video_path,
                config_path=args.config,
                work_dir=args.output_dir / "_work",
                question=args.question,
                resolved_intent=shared_intent,
                llm_backend=args.llm_backend,
                llm_model=args.llm_model,
                runner_fn=runner_fn,
            )
            rows.append(row)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = summarize_paired_eval(
        rows,
        annotations,
        min_evaluable_positives=args.min_evaluable_positives,
        min_evaluable_negatives=args.min_evaluable_negatives,
        recall_tolerance=args.recall_tolerance,
        fp_rate_tolerance=args.fp_rate_tolerance,
        max_failure_rate=args.max_failure_rate,
        contract_version=contract_version,
    )
    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report_path = args.output_dir / "REPORT.md"
    report_path.write_text(render_markdown_report(summary), encoding="utf-8")
    print(json.dumps(summary["decision"], ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    main()
