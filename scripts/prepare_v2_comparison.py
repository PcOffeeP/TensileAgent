#!/usr/bin/env python3
"""Freeze the V2 comparison identity after V4.1 Stage G finalization."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import requests

from agent.v2_comparison_batch import (
    build_v2_comparison_manifest,
    freeze_v2_comparison_manifest,
)
from agent.v2_comparison_scoring import build_v4_common_baseline


ROOT = Path(__file__).resolve().parents[1]


def _write_json_once(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != value:
            raise ValueError(f"refusing to overwrite evidence: {path}")
        return
    temporary = path.with_name(f".{path.name}.tmp")
    data = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--v4-acceptance-manifest", required=True)
    parser.add_argument("--v4-finalization-manifest", required=True)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--v4-results-root", required=True)
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
    baseline = build_v4_common_baseline(
        v4_acceptance_manifest_path=args.v4_acceptance_manifest,
        v4_finalization_manifest_path=args.v4_finalization_manifest,
        annotations_path=args.annotations,
        results_root=args.v4_results_root,
    )
    baseline_path = (
        args.output_root / "v4_common_baselines" / f"{baseline['baseline_id']}.json"
    )
    _write_json_once(baseline_path, baseline)
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
        comparison_scorer_path=ROOT / "agent/v2_comparison_scoring.py",
        comparison_finalizer_path=ROOT / "agent/v2_comparison_finalizer.py",
        annotations_path=args.annotations,
        v4_common_baseline_path=baseline_path,
        service_snapshot=snapshot,
        agent_runtime_commit=commit,
        batch_runner_path=runner_path,
    )
    output = args.output_root / manifest["manifest_id"] / "v2_comparison_manifest.json"
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
