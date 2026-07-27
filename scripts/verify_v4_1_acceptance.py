#!/usr/bin/env python3
"""Verify the complete Stage G chain before scoring or unsealing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent.acceptance_verifier import verify_acceptance_run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--stage-g-authorization", required=True)
    parser.add_argument("--results-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = verify_acceptance_run(
        args.manifest,
        args.stage_g_authorization,
        args.results_root,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
