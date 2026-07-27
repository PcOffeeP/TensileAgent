#!/usr/bin/env python3
"""Validate the single-center intermediate delivery bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
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


def is_ancestor(root: Path, commit: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    ).returncode == 0


def validate(root: Path = ROOT, mvllm_root: Path | None = None) -> dict[str, Any]:
    bundle_path = root / "delivery/current/bundle.json"
    bundle = load_object(bundle_path)
    errors: list[str] = []
    if bundle.get("schema_version") != "tensile-delivery/bundle/v2":
        errors.append("invalid bundle schema")
    if bundle.get("disposition") != "intermediate_development_model":
        errors.append("invalid delivery disposition")
    quality = bundle.get("historical_quality_status", {})
    expected_quality = {
        "stage_b_passed": False,
        "stage_c_completed": False,
        "stage_d_passed": False,
        "stage_g_passed": False,
        "production_approved": False,
    }
    if quality != expected_quality:
        errors.append("historical quality status must preserve failed/deferred facts")
    performance_policy = bundle.get("performance_policy", {})
    expected_performance_policy = {
        "mode": "record_only_non_blocking",
        "thresholds_evaluated_for_delivery": False,
        "blocks_intermediate_delivery": False,
        "optimization_status": "paused",
        "retraining_authorized": False,
    }
    if performance_policy != expected_performance_policy:
        errors.append("performance policy must remain record-only and non-blocking")
    delivery_gate = bundle.get("delivery_gate", {})
    checks = delivery_gate.get("checks", {})
    required_chain_checks = {
        "component_manifests_validated",
        "cross_repository_identity_verified",
        "model_full_hash_verified",
        "service_contract_verified",
        "agent_tests_passed",
        "web_build_passed",
        "real_video_remote_gpu_call_passed",
        "transport_fail_closed_verified",
        "git_sync_verified",
    }
    if (
        delivery_gate.get("overall_passed") is not True
        or set(checks) != required_chain_checks
        or not all(checks.get(name) is True for name in required_chain_checks)
    ):
        errors.append("end-to-end delivery gate is incomplete")
    required_claims = {
        "final",
        "full-data",
        "independent-test-passed",
        "production-approved",
    }
    if set(bundle.get("prohibited_claims", [])) != required_claims:
        errors.append("prohibited claims are incomplete")
    for name in ("product_card", "v2_rollback"):
        binding = bundle.get("documentation", {}).get(name, {})
        path = root / str(binding.get("path", ""))
        if not path.is_file() or sha256(path) != binding.get("sha256"):
            errors.append(f"{name} documentation hash mismatch")

    loaded: dict[str, dict[str, Any]] = {}
    for name in ("agent", "model", "service", "acceptance", "performance"):
        binding = bundle.get("components", {}).get(name, {})
        path = root / str(binding.get("path", ""))
        if not path.is_file():
            errors.append(f"{name} component missing")
            continue
        if sha256(path) != binding.get("sha256"):
            errors.append(f"{name} component hash mismatch")
            continue
        loaded[name] = load_object(path)

    agent = loaded.get("agent", {})
    if (
        agent.get("capability", {}).get("production_approved") is not False
        or agent.get("capability", {}).get("full_data_final") is not False
        or agent.get("capability", {}).get("independent_test_passed") is not False
    ):
        errors.append("agent capability boundary is invalid")
    for field in ("runtime_source_commit", "delivery_lineage_commit"):
        commit = str(agent.get(field, ""))
        if not commit or not is_ancestor(root, commit):
            errors.append(f"agent {field} is not in repository ancestry")

    model = loaded.get("model", {})
    service = loaded.get("service", {})
    acceptance = loaded.get("acceptance", {})
    if model.get("model_tier") != "intermediate_development_model":
        errors.append("model tier mismatch")
    if service.get("runtime", {}).get("access_policy") != "ssh_tunnel_only":
        errors.append("service access policy must be ssh_tunnel_only")
    if service.get("runtime", {}).get("host") != "127.0.0.1":
        errors.append("service must remain loopback-only")
    if acceptance.get("historical_quality_status") != expected_quality:
        errors.append("acceptance summary historical quality status mismatch")
    performance = loaded.get("performance", {})
    if performance.get("policy") != expected_performance_policy:
        errors.append("performance snapshot policy mismatch")
    if not isinstance(performance.get("metrics"), dict) or not performance.get("metrics"):
        errors.append("performance snapshot metrics are missing")

    validation_path = root / "delivery/current/validation.json"
    if validation_path.is_file():
        validation = load_object(validation_path)
        if validation.get("bundle", {}).get("sha256") != sha256(bundle_path):
            errors.append("validation report bundle hash mismatch")
        if validation.get("historical_quality_status") != expected_quality:
            errors.append("validation report historical quality status mismatch")
        if validation.get("performance_policy") != expected_performance_policy:
            errors.append("validation report performance policy mismatch")
        if validation.get("delivery_gate") != delivery_gate:
            errors.append("validation report delivery gate mismatch")

    core_steps_path = root / "delivery/current/core_step_results.json"
    if not core_steps_path.is_file():
        errors.append("core step results are missing")
    else:
        core_steps = load_object(core_steps_path)
        steps = core_steps.get("steps", [])
        if (
            core_steps.get("overall_chain_passed") is not True
            or core_steps.get("performance_is_a_delivery_gate") is not False
            or not isinstance(steps, list)
            or len(steps) != 9
            or any(
                step.get("status") not in {"passed", "recorded_non_blocking"}
                for step in steps
            )
        ):
            errors.append("core step results are incomplete")
        if core_steps.get("historical_quality_status") != expected_quality:
            errors.append("core step historical quality status mismatch")

    if mvllm_root is not None:
        for name in ("model", "service"):
            canonical = bundle.get("canonical_sources", {}).get(name, {})
            source = mvllm_root / str(canonical.get("path", ""))
            snapshot = root / bundle["components"][name]["path"]
            if not source.is_file():
                errors.append(f"canonical {name} component missing")
            elif sha256(source) != canonical.get("sha256"):
                errors.append(f"canonical {name} component hash mismatch")
            elif source.read_bytes() != snapshot.read_bytes():
                errors.append(f"{name} snapshot differs from canonical source")

    return {
        "schema_version": "tensile-delivery/bundle-validation/v2",
        "bundle_sha256": sha256(bundle_path),
        "component_count": len(loaded),
        "cross_repository_checked": mvllm_root is not None,
        "errors": errors,
        "passed": not errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--mvllm-root", type=Path)
    args = parser.parse_args()
    report = validate(
        args.root.resolve(),
        args.mvllm_root.resolve() if args.mvllm_root else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
