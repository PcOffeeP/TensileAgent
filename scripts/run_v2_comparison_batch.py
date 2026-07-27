#!/usr/bin/env python3
"""Run the frozen, resumable all_110 V2 comparison."""

from __future__ import annotations

import argparse
import json

from agent.v2_comparison_batch import run_v2_comparison_batch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args()
    summary = run_v2_comparison_batch(
        args.manifest,
        args.output_dir,
        retry_failed=args.retry_failed,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    raise SystemExit(0 if summary["failed_or_pending_retry"] == 0 else 1)


if __name__ == "__main__":
    main()
