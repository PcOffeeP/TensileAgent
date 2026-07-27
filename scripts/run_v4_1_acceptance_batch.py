#!/usr/bin/env python3
"""Run the frozen V4.1 acceptance batch with resumable per-video outputs."""

from __future__ import annotations

import argparse
import json

from agent.acceptance_batch import run_acceptance_batch


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--input-list", default="all_110")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument(
        "--stage-g-authorization",
        help="Frozen one-time authorization required for all_110 or heldout_21",
    )
    args = parser.parse_args()
    summary = run_acceptance_batch(
        args.manifest,
        args.output_dir,
        list_name=args.input_list,
        retry_failed=args.retry_failed,
        stage_g_authorization_path=args.stage_g_authorization,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    raise SystemExit(0 if summary["failed_or_pending_retry"] == 0 else 1)


if __name__ == "__main__":
    main()
