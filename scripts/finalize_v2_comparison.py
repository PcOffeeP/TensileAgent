#!/usr/bin/env python3
"""Finalize the frozen V2 versus V4.1 comparison."""

from __future__ import annotations

import argparse
import json

from agent.v2_comparison_finalizer import finalize_v2_comparison


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--v2-results-root", required=True)
    parser.add_argument("--output-root", required=True)
    args = parser.parse_args()
    report = finalize_v2_comparison(
        args.manifest,
        args.v2_results_root,
        args.output_root,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
