#!/usr/bin/env python3
"""Freeze the V2 comparison identity after V4.1 Stage G finalization."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import requests

from agent.v2_comparison_batch import (
    build_v2_comparison_manifest,
    freeze_v2_comparison_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v4-acceptance-manifest", required=True)
    parser.add_argument("--v4-finalization-manifest", required=True)
    parser.add_argument(
        "--config",
        default=ROOT / "agent/config.v2.comparison.yaml",
        type=Path,
    )
    parser.add_argument(
        "--comparison-spec",
        default=ROOT / "agent/scoring/v2_comparison_v1.json",
        type=Path,
    )
    parser.add_argument(
        "--contract-url",
        default="http://127.0.0.1:8001/v1/tensile/contract",
    )
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args()
    response = requests.get(args.contract_url, timeout=10)
    response.raise_for_status()
    snapshot = response.json()
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    runner_path = ROOT / "scripts/run_v2_comparison_batch.py"
    manifest = build_v2_comparison_manifest(
        v4_acceptance_manifest_path=args.v4_acceptance_manifest,
        v4_finalization_manifest_path=args.v4_finalization_manifest,
        config_path=args.config,
        comparison_spec_path=args.comparison_spec,
        service_snapshot=snapshot,
        agent_runtime_commit=commit,
        batch_runner_path=runner_path,
    )
    output = (
        args.output_root
        / manifest["manifest_id"]
        / "v2_comparison_manifest.json"
    )
    freeze_v2_comparison_manifest(output, manifest)
    print(
        json.dumps(
            {
                "manifest_id": manifest["manifest_id"],
                "manifest_path": str(output.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
