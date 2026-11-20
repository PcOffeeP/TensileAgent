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


REQUIRED_DELIVERY_CHECKS = (
    "component_manifests_validated",
    "cross_repository_identity_verified",
    "model_full_hash_verified",
    "service_contract_verified",
    "agent_tests_passed",
    "web_build_passed",
    "real_video_remote_gpu_call_passed",
    "transport_fail_closed_verified",
    "git_sync_verified",
)


def _load_delivery_gate(
    verification_record: Path | None,
) -> dict[str, Any]:
    """Build delivery_gate strictly from recorded verification evidence.

    Any check not explicitly attested as ``True`` in ``verification_record`` is
    recorded as ``"unverified"`` so running the generator alone can never forge
    test, GPU, or git-sync passes.
    """
    recorded_checks: dict[str, Any] = {}
    if verification_record is not None and verification_record.is_file():
        payload = load_object(verification_record)
        candidate = payload.get("checks")
        if not isinstance(candidate, dict):
            candidate = (payload.get("delivery_gate") or {}).get("checks")
        if isinstance(candidate, dict):
            recorded_checks = candidate
    checks = {
        name: (True if recorded_checks.get(name) is True else "unverified")
        for name in REQUIRED_DELIVERY_CHECKS
    }
    return {
        "overall_passed": all(value is True for value in checks.values()),
        "checks": checks,
    }


def generate(
    root: Path,
    mvllm_root: Path,
    *,
    verification_record: Path | None = None,
) -> dict[str, Any]:
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
        "performance": "docs/results/v4_1_stage_g_intermediate/performance_snapshot.json",
    }
    bundle = {
        "schema_version": "tensile-delivery/bundle/v2",
        "bundle_name": "v4.1-agent-pipeline-fold0-r1",
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
        "documentation": {
            "product_card": {
                "path": "delivery/current/PRODUCT_CARD.md",
                "sha256": sha256(root / "delivery/current/PRODUCT_CARD.md"),
            },
            "v2_rollback": {
                "path": "delivery/rollback/V2_ROLLBACK.md",
                "sha256": sha256(root / "delivery/rollback/V2_ROLLBACK.md"),
            },
        },
        "delivery_gate": _load_delivery_gate(verification_record),
        "performance_policy": {
            "mode": "record_only_non_blocking",
            "thresholds_evaluated_for_delivery": False,
            "blocks_intermediate_delivery": False,
            "optimization_status": "paused",
            "retraining_authorized": False,
        },
        "historical_quality_status": {
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
    parser.add_argument(
        "--verification-record",
        type=Path,
        default=None,
        help="Optional JSON file attesting completed verification checks; unattested checks stay unverified.",
    )
    args = parser.parse_args()
    bundle = generate(
        args.root.resolve(),
        args.mvllm_root.resolve(),
        verification_record=(
            args.verification_record.resolve()
            if args.verification_record is not None
            else None
        ),
    )
    print(json.dumps(bundle, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
