#!/usr/bin/env python3
"""Verify and score the completed one-time V4.1 Stage G run."""

from __future__ import annotations

import argparse
import json

from agent.acceptance_finalizer import finalize_stage_g


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--stage-g-authorization", required=True)
    parser.add_argument("--scoring-addendum", required=True)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--results-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    report = finalize_stage_g(
        args.manifest,
        args.stage_g_authorization,
        args.scoring_addendum,
        args.annotations,
        args.results_root,
        args.output_root,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
