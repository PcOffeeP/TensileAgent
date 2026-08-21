#!/usr/bin/env python3
"""Score a completed V4.1 batch with the frozen scoring implementation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.scoring_v4_1 import (
    evaluate_thresholds,
    load_scoring_records,
    score_predictions,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--results-root", required=True)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--video-ids", help="Optional JSON array restricting the scored subset"
    )
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    allowed = None
    if args.video_ids:
        allowed = set(json.loads(Path(args.video_ids).read_text(encoding="utf-8")))
    records = load_scoring_records(
        args.annotations,
        args.results_root,
        allowed_video_ids=allowed,
    )
    report = score_predictions(records)
    report["threshold_evaluation"] = evaluate_thresholds(
        report,
        spec["thresholds"],
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
