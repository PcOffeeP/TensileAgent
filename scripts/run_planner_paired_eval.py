#!/usr/bin/env python3
"""Run paired evaluation comparing DeterministicPlanner vs LLM planner on the same V4.1 Runtime."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from agent.planner_paired_eval import (
    render_markdown_report,
    run_paired_video,
    summarize_paired_eval,
)
from agent.scoring_v4_1 import load_annotations
from agent.strategy_ab import DIAGNOSTIC_30_IDS


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Paired evaluation of DeterministicPlanner vs LLM planner under identical V4.1 Runtime constraints."
    )
    parser.add_argument("--videos-root", type=Path, required=True, help="Directory containing <video_id>.mp4 files.")
    parser.add_argument("--annotations", type=Path, required=True, help="Ground-truth CSV/JSONL annotations file.")
    parser.add_argument("--config", type=Path, default=Path("agent/config.yaml"), help="Base V4.1 config YAML.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory to write ledger, summary, and report.")
    parser.add_argument(
        "--video-ids",
        nargs="*",
        default=None,
        help="Optional subset of video IDs; defaults to diagnostic30 intersection with annotations.",
    )
    parser.add_argument("--llm-backend", choices=("local", "remote"), default="local")
    parser.add_argument("--llm-model", default=None, help="Optional override for the LLM planner model name.")
    parser.add_argument("--question", default="请完整分析这段拉伸试验视频")
    parser.add_argument("--min-evaluable-positives", type=int, default=10)
    parser.add_argument("--recall-tolerance", type=float, default=0.05)
    parser.add_argument("--fp-rate-tolerance", type=float, default=0.05)
    parser.add_argument("--mock", action="store_true", help="Enable INFERENCE_MOCK=1 for offline smoke runs.")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    if args.mock:
        os.environ["INFERENCE_MOCK"] = "1"

    annotations = load_annotations(args.annotations)
    if args.video_ids:
        target_ids = list(args.video_ids)
    else:
        target_ids = [vid for vid in DIAGNOSTIC_30_IDS if vid in annotations]
        if not target_ids:
            target_ids = sorted(annotations.keys())

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
                llm_backend=args.llm_backend,
                llm_model=args.llm_model,
            )
            rows.append(row)
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = summarize_paired_eval(
        rows,
        annotations,
        min_evaluable_positives=args.min_evaluable_positives,
        recall_tolerance=args.recall_tolerance,
        fp_rate_tolerance=args.fp_rate_tolerance,
    )
    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report_path = args.output_dir / "REPORT.md"
    report_path.write_text(render_markdown_report(summary), encoding="utf-8")
    print(json.dumps(summary["decision"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
