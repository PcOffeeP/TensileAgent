#!/usr/bin/env python3
"""Generate the lightweight, single-center intermediate delivery bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def generate(root: Path, mvllm_root: Path) -> dict[str, Any]:
    components = root / "delivery/components"
    sources = {
        "model": mvllm_root / "delivery/model_component.json",
        "service": mvllm_root / "delivery/service_component.json",
    }
    for name, source in sources.items():
        if not source.is_file():
            raise FileNotFoundError(source)
        target = components / f"{name}_component.json"
        shutil.copyfile(source, target)

    paths = {
        "agent": "delivery/components/agent_component.json",
        "model": "delivery/components/model_component.json",
        "service": "delivery/components/service_component.json",
        "acceptance": "docs/results/v4_1_stage_g_intermediate/acceptance_summary.json",
    }
    bundle = {
        "schema_version": "tensile-delivery/bundle/v1",
        "bundle_name": "v4.1-intermediate-development-2026-07-27",
        "disposition": "intermediate_development_model",
        "components": {
            name: {"path": path, "sha256": sha256(root / path)}
            for name, path in paths.items()
        },
        "canonical_sources": {
            "model": {
                "repository": "mVllm_2",
                "path": "delivery/model_component.json",
                "sha256": sha256(sources["model"]),
            },
            "service": {
                "repository": "mVllm_2",
                "path": "delivery/service_component.json",
                "sha256": sha256(sources["service"]),
            },
        },
        "quality_status": {
            "stage_b_passed": False,
            "stage_c_completed": False,
            "stage_d_passed": False,
            "stage_g_passed": False,
            "production_approved": False,
        },
        "prohibited_claims": [
            "final",
            "full-data",
            "independent-test-passed",
            "production-approved",
        ],
    }
    write_json(root / "delivery/current/bundle.json", bundle)
    return bundle


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--mvllm-root", type=Path, required=True)
    args = parser.parse_args()
    bundle = generate(args.root.resolve(), args.mvllm_root.resolve())
    print(json.dumps(bundle, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

