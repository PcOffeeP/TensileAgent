"""Atomic finalization of the frozen V2 versus V4.1 comparison."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from agent.acceptance_batch import sha256_file
from agent.v2_comparison_batch import load_v2_comparison_manifest
from agent.v2_comparison_scoring import (
    compare_common_reports,
    compare_special_cases,
    load_common_records,
    score_common,
    validate_v2_result_identity,
)


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()


def _atomic_write_once(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    if path.exists() or temporary.exists():
        raise ValueError(f"refusing to overwrite comparison evidence: {path}")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(_canonical_bytes(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if temporary.exists():
            temporary.unlink()
        raise


def _load_bound_finalization(manifest: dict[str, Any]) -> dict[str, Any]:
    binding = manifest["v4_acceptance"]
    path = Path(binding["finalization_manifest_path"]).resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        value.get("schema_version") != "tensile-agent/stage-g-finalization/v1"
        or value.get("finalization_id") != binding["finalization_id"]
        or sha256_file(path) != binding["finalization_manifest_sha256"]
    ):
        raise ValueError("bound V4.1 finalization identity mismatch")
    for name, expected_hash in value.get("artifacts", {}).items():
        artifact = path.parent / name
        if not artifact.is_file() or sha256_file(artifact) != expected_hash:
            raise ValueError(f"V4.1 finalization artifact mismatch: {name}")
    return value


def finalize_v2_comparison(
    manifest_path: str | Path,
    v2_results_root: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    """Verify, score, compare, and freeze the final acceptance decision."""
    manifest = load_v2_comparison_manifest(manifest_path)
    chain = validate_v2_result_identity(manifest_path, v2_results_root)
    if chain["passed"] is not True:
        raise ValueError("V2 comparison chain integrity failed")
    finalization = _load_bound_finalization(manifest)

    spec_path = Path(manifest["comparison_spec"]["path"])
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if (
        spec.get("schema_version") != "tensile-agent/v2-comparison-spec/v1"
        or spec.get("comparison_version") != "v2-v4.1-common-metrics-v1"
    ):
        raise ValueError("invalid V2 comparison specification")
    baseline = json.loads(
        Path(manifest["v4_common_baseline"]["path"]).read_text(encoding="utf-8")
    )
    if (
        baseline.get("schema_version") != "tensile-agent/v4-common-baseline/v1"
        or baseline.get("annotations_sha256") != manifest["annotations"]["sha256"]
        or baseline.get("v4_finalization_manifest_sha256")
        != manifest["v4_acceptance"]["finalization_manifest_sha256"]
    ):
        raise ValueError("V4.1 common baseline binding mismatch")
    v4_report = baseline.get("report")
    if not isinstance(v4_report, dict):
        raise ValueError("V4.1 common baseline report is missing")

    input_rows = json.loads(
        Path(manifest["input_list"]["path"]).read_text(encoding="utf-8")
    )
    video_ids = {row["video_id"] for row in input_rows}
    v2_report = score_common(
        load_common_records(
            manifest["annotations"]["path"],
            v2_results_root,
            schema_version="tensile-agent/result/v2",
            allowed_video_ids=video_ids,
            manifest_hash_field="v2_comparison_manifest_sha256",
            expected_manifest_hash=manifest["_sha256"],
        )
    )
    tolerance = spec.get("regression_rule", {}).get("absolute_tolerance")
    if not isinstance(tolerance, (int, float)) or not 0 <= tolerance < 1:
        raise ValueError("invalid V2 comparison tolerance")
    numeric = compare_common_reports(
        v4_report,
        v2_report,
        absolute_tolerance=float(tolerance),
    )
    special = compare_special_cases(v4_report, v2_report)
    stage_g_before_v2 = finalization.get("stage_g_gate", {}).get(
        "passed_before_v2_comparison"
    )
    final_gate = {
        "stage_g_passed_before_v2_comparison": stage_g_before_v2 is True,
        "v2_chain_integrity_passed": True,
        "numeric_non_regression_passed": numeric["passed"],
        "special_case_comparison_passed": special["passed"],
        "final_acceptance_passed": (
            stage_g_before_v2 is True and numeric["passed"] and special["passed"]
        ),
    }

    identity = {
        "v2_comparison_manifest_id": manifest["manifest_id"],
        "v2_comparison_manifest_sha256": manifest["_sha256"],
        "v4_finalization_manifest_sha256": manifest["v4_acceptance"][
            "finalization_manifest_sha256"
        ],
        "v4_common_baseline_sha256": manifest["v4_common_baseline"]["sha256"],
        "annotations_sha256": manifest["annotations"]["sha256"],
        "comparison_spec_sha256": manifest["comparison_spec"]["sha256"],
        "comparison_scorer_sha256": manifest["comparison_scorer"]["sha256"],
        "comparison_finalizer_sha256": manifest["comparison_finalizer"]["sha256"],
    }
    comparison_id = (
        "v2-comparison-finalization-"
        + hashlib.sha256(
            json.dumps(
                identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:12]
    )
    output_dir = Path(output_root).resolve() / comparison_id
    output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    artifacts = {
        "v2_chain_integrity_report.json": chain,
        "v4_1_common_report.json": v4_report,
        "v2_common_report.json": v2_report,
        "numeric_non_regression_report.json": numeric,
        "special_case_comparison_report.json": special,
        "final_acceptance_gate.json": final_gate,
    }
    artifact_hashes: dict[str, str] = {}
    for name, value in artifacts.items():
        path = output_dir / name
        _atomic_write_once(path, value)
        artifact_hashes[name] = sha256_file(path)
    completion = {
        "schema_version": "tensile-agent/v2-comparison-finalization/v1",
        "comparison_finalization_id": comparison_id,
        "inputs": identity,
        "artifacts": artifact_hashes,
        "final_gate": final_gate,
        "status": "complete",
    }
    completion_path = output_dir / "comparison_finalization_manifest.json"
    _atomic_write_once(completion_path, completion)
    return {
        **completion,
        "output_dir": str(output_dir),
        "comparison_finalization_manifest_sha256": sha256_file(completion_path),
    }
