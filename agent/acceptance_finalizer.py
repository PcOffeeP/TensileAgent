"""Atomic post-run scoring for the single frozen V4.1 Stage G run."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from agent.acceptance_batch import (
    load_acceptance_manifest,
    load_bound_input_list,
    load_stage_g_authorization,
    sha256_file,
)
from agent.acceptance_verifier import verify_acceptance_run
from agent.acceptance_reporting import (
    build_diagnostic_report,
    summarize_batch_timing,
)
from agent.scoring_v4_1 import (
    evaluate_thresholds,
    load_scoring_records,
    score_predictions,
)


ROOT = Path(__file__).resolve().parents[1]
SCORER_PATH = ROOT / "agent/scoring_v4_1.py"
SPEC_PATH = ROOT / "agent/scoring/v4_1_agent_acceptance_v1.json"
REPORTER_PATH = ROOT / "agent/acceptance_reporting.py"
FINALIZER_PATH = ROOT / "agent/acceptance_finalizer.py"


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    ).encode()


def _atomic_write_once(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    if path.exists() or temporary.exists():
        raise ValueError(f"refusing to overwrite finalization artifact: {path}")
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


def _special_case_gate(
    report: dict[str, Any],
    expected: str,
) -> dict[str, Any]:
    try:
        expected_correct, expected_total = (
            int(value) for value in expected.split("/", 1)
        )
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError("special_case_exact must use N/N syntax") from exc
    rows = report.get("special_case_results")
    if not isinstance(rows, list):
        raise ValueError("score report missing special_case_results")
    actual_total = len(rows)
    actual_correct = sum(
        isinstance(row, dict) and row.get("correct") is True for row in rows
    )
    return {
        "actual": f"{actual_correct}/{actual_total}",
        "minimum": expected,
        "passed": (
            actual_total == expected_total and actual_correct >= expected_correct
        ),
    }


def finalize_stage_g(
    manifest_path: str | Path,
    authorization_path: str | Path,
    scoring_addendum_path: str | Path,
    annotations_path: str | Path,
    results_root: str | Path,
    output_root: str | Path,
) -> dict[str, Any]:
    """Verify, score, and freeze reports without rerunning any video."""
    manifest = load_acceptance_manifest(manifest_path)
    authorization = load_stage_g_authorization(
        authorization_path,
        manifest,
        "all_110",
    )
    chain = verify_acceptance_run(
        manifest_path,
        authorization_path,
        results_root,
    )
    if chain["passed"] is not True:
        raise ValueError("chain integrity failed; scoring is forbidden")

    addendum_path = Path(scoring_addendum_path).resolve()
    addendum = json.loads(addendum_path.read_text(encoding="utf-8"))
    annotations = Path(annotations_path).resolve()
    if (
        addendum.get("schema_version")
        != "tensile-agent/stage-g-scoring-input-addendum/v1"
        or addendum.get("one_time_run_id") != authorization["one_time_run_id"]
        or addendum.get("agent_acceptance_manifest_sha256") != manifest["_sha256"]
        or addendum.get("stage_g_authorization_sha256") != authorization["_sha256"]
        or addendum.get("annotations_path") != str(annotations)
        or addendum.get("annotations_sha256") != sha256_file(annotations)
        or addendum.get("frozen_before_scoring") is not True
    ):
        raise ValueError("Stage G scoring addendum identity mismatch")
    if (
        sha256_file(SCORER_PATH) != manifest["scoring"]["implementation_sha256"]
        or sha256_file(SPEC_PATH) != manifest["scoring"]["spec_sha256"]
    ):
        raise ValueError("frozen scorer/spec identity mismatch")

    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    all_inputs = load_bound_input_list(manifest, "all_110")
    heldout_inputs = load_bound_input_list(manifest, "heldout_21")
    all_ids = {row["video_id"] for row in all_inputs}
    heldout_ids = {row["video_id"] for row in heldout_inputs}
    if not heldout_ids < all_ids:
        raise ValueError("heldout_21 must be a strict subset of all_110")
    development_ids = all_ids - heldout_ids

    all_records = load_scoring_records(
        annotations,
        results_root,
        allowed_video_ids=all_ids,
    )
    heldout_records = load_scoring_records(
        annotations,
        results_root,
        allowed_video_ids=heldout_ids,
    )
    development_records = load_scoring_records(
        annotations,
        results_root,
        allowed_video_ids=development_ids,
    )
    all_report = score_predictions(all_records)
    heldout_report = score_predictions(heldout_records)
    development_report = score_predictions(development_records)
    for name, report in (
        ("all_110", all_report),
        ("heldout_21", heldout_report),
        ("development_89", development_report),
    ):
        report["subset"] = name
        report["threshold_evaluation"] = evaluate_thresholds(
            report,
            spec["thresholds"],
        )

    special_case_gate = _special_case_gate(
        all_report,
        spec["thresholds"]["special_case_exact"],
    )
    stage_g_gate = {
        "chain_integrity_passed": True,
        "heldout_21_numeric_thresholds_passed": heldout_report["threshold_evaluation"][
            "passed"
        ],
        "all_110_special_case_exact": special_case_gate,
        "passed_before_v2_comparison": (
            heldout_report["threshold_evaluation"]["passed"]
            and special_case_gate["passed"]
        ),
        "v2_comparison_required": True,
        "final_acceptance_pending_v2_comparison": True,
    }

    seed = {
        "one_time_run_id": authorization["one_time_run_id"],
        "manifest_sha256": manifest["_sha256"],
        "authorization_sha256": authorization["_sha256"],
        "addendum_sha256": sha256_file(addendum_path),
        "annotations_sha256": sha256_file(annotations),
        "scorer_sha256": sha256_file(SCORER_PATH),
        "spec_sha256": sha256_file(SPEC_PATH),
        "reporter_sha256": sha256_file(REPORTER_PATH),
        "finalizer_sha256": sha256_file(FINALIZER_PATH),
    }
    finalization_id = (
        "stage-g-finalization-"
        + hashlib.sha256(
            json.dumps(
                seed,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()[:12]
    )
    output_dir = Path(output_root).resolve() / finalization_id
    output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(output_dir, 0o700)
    artifacts = {
        "chain_integrity_report.json": chain,
        "all_110_accuracy_report.json": all_report,
        "heldout_21_accuracy_report.json": heldout_report,
        "development_89_accuracy_report.json": development_report,
        "all_110_diagnostic_report.json": build_diagnostic_report(all_records),
        "heldout_21_diagnostic_report.json": build_diagnostic_report(heldout_records),
        "development_89_diagnostic_report.json": build_diagnostic_report(
            development_records
        ),
        "batch_timing_report.json": summarize_batch_timing(
            results_root,
            all_ids,
        ),
        "stage_g_gate.json": stage_g_gate,
    }
    artifact_hashes: dict[str, str] = {}
    for name, value in artifacts.items():
        path = output_dir / name
        _atomic_write_once(path, value)
        artifact_hashes[name] = sha256_file(path)
    finalization_manifest = {
        "schema_version": "tensile-agent/stage-g-finalization/v1",
        "finalization_id": finalization_id,
        "one_time_run_id": authorization["one_time_run_id"],
        "inputs": seed,
        "subsets": {
            "all_110": len(all_ids),
            "heldout_21": len(heldout_ids),
            "development_89": len(development_ids),
        },
        "artifacts": artifact_hashes,
        "stage_g_gate": stage_g_gate,
        "status": "scored_awaiting_v2_comparison",
    }
    _atomic_write_once(
        output_dir / "finalization_manifest.json",
        finalization_manifest,
    )
    return {
        **finalization_manifest,
        "output_dir": str(output_dir),
        "finalization_manifest_sha256": sha256_file(
            output_dir / "finalization_manifest.json"
        ),
    }
