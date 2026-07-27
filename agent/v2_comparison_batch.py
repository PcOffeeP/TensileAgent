"""Identity-bound preparation and batch execution for the V2 comparison."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.acceptance_batch import sha256_file
from agent.runner import run_one


MANIFEST_SCHEMA = "tensile-agent/v2-comparison-manifest/v1"
BATCH_SCHEMA = "tensile-agent/v2-comparison-batch/v1"


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


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_bytes(_canonical_bytes(value))
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def build_v2_comparison_manifest(
    *,
    v4_acceptance_manifest_path: str | Path,
    v4_finalization_manifest_path: str | Path,
    config_path: str | Path,
    comparison_spec_path: str | Path,
    comparison_scorer_path: str | Path,
    comparison_finalizer_path: str | Path,
    annotations_path: str | Path,
    v4_common_baseline_path: str | Path,
    service_snapshot: dict[str, Any],
    agent_runtime_commit: str,
    batch_runner_path: str | Path,
) -> dict[str, Any]:
    """Build the immutable identity for the post-V4.1 V2 baseline."""
    v4_manifest_path = Path(v4_acceptance_manifest_path).resolve()
    v4_manifest = json.loads(v4_manifest_path.read_text(encoding="utf-8"))
    finalization_path = Path(v4_finalization_manifest_path).resolve()
    finalization = json.loads(finalization_path.read_text(encoding="utf-8"))
    if (
        finalization.get("schema_version")
        != "tensile-agent/stage-g-finalization/v1"
        or finalization.get("status") != "scored_awaiting_v2_comparison"
        or finalization.get("stage_g_gate", {}).get(
            "final_acceptance_pending_v2_comparison"
        )
        is not True
    ):
        raise ValueError("V4.1 Stage G finalization is not ready for V2")
    if (
        v4_manifest.get("schema_version")
        != "tensile-agent/acceptance-manifest/v1"
        or v4_manifest.get("status") != "frozen"
    ):
        raise ValueError("invalid V4.1 acceptance manifest")
    deployment = service_snapshot.get("deployment_manifest")
    if (
        service_snapshot.get("contract_version") != "tensile-vlm/v2"
        or not isinstance(deployment, dict)
        or deployment.get("contract_version") != "tensile-vlm/v2"
    ):
        raise ValueError("V2 service snapshot is invalid")

    config = Path(config_path).resolve()
    spec = Path(comparison_spec_path).resolve()
    scorer = Path(comparison_scorer_path).resolve()
    finalizer = Path(comparison_finalizer_path).resolve()
    annotations = Path(annotations_path).resolve()
    baseline = Path(v4_common_baseline_path).resolve()
    runner = Path(batch_runner_path).resolve()
    all_110 = v4_manifest["input_lists"]["all_110"]
    baseline_value = json.loads(baseline.read_text(encoding="utf-8"))
    if (
        baseline_value.get("schema_version")
        != "tensile-agent/v4-common-baseline/v1"
        or baseline_value.get("v4_acceptance_manifest_sha256")
        != sha256_file(v4_manifest_path)
        or baseline_value.get("v4_finalization_manifest_sha256")
        != sha256_file(finalization_path)
        or baseline_value.get("annotations_sha256")
        != sha256_file(annotations)
        or baseline_value.get("video_count") != all_110["count"]
    ):
        raise ValueError("V4.1 common baseline identity mismatch")
    seed = {
        "v4_acceptance_manifest_sha256": sha256_file(v4_manifest_path),
        "v4_finalization_manifest_sha256": sha256_file(finalization_path),
        "input_list_sha256": all_110["sha256"],
        "config_sha256": sha256_file(config),
        "comparison_spec_sha256": sha256_file(spec),
        "comparison_scorer_sha256": sha256_file(scorer),
        "comparison_finalizer_sha256": sha256_file(finalizer),
        "annotations_sha256": sha256_file(annotations),
        "v4_common_baseline_sha256": sha256_file(baseline),
        "service_snapshot": service_snapshot,
        "agent_runtime_commit": agent_runtime_commit,
        "batch_runner_sha256": sha256_file(runner),
    }
    manifest_id = "v2-comparison-" + hashlib.sha256(
        json.dumps(
            seed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()[:12]
    return {
        "schema_version": MANIFEST_SCHEMA,
        "manifest_id": manifest_id,
        "status": "frozen",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "v4_acceptance": {
            "manifest_id": v4_manifest["manifest_id"],
            "manifest_path": str(v4_manifest_path),
            "manifest_sha256": sha256_file(v4_manifest_path),
            "finalization_id": finalization["finalization_id"],
            "finalization_manifest_path": str(finalization_path),
            "finalization_manifest_sha256": sha256_file(finalization_path),
        },
        "agent_runtime_commit": agent_runtime_commit,
        "question": v4_manifest["question"],
        "input_list": {
            "name": "all_110",
            "path": all_110["path"],
            "sha256": all_110["sha256"],
            "count": all_110["count"],
        },
        "config": {
            "path": str(config),
            "sha256": sha256_file(config),
        },
        "comparison_spec": {
            "path": str(spec),
            "sha256": sha256_file(spec),
        },
        "comparison_scorer": {
            "path": str(scorer),
            "sha256": sha256_file(scorer),
        },
        "comparison_finalizer": {
            "path": str(finalizer),
            "sha256": sha256_file(finalizer),
        },
        "annotations": {
            "path": str(annotations),
            "sha256": sha256_file(annotations),
        },
        "v4_common_baseline": {
            "path": str(baseline),
            "sha256": sha256_file(baseline),
        },
        "service_snapshot": service_snapshot,
        "batch_runner": {
            "path": str(runner),
            "sha256": sha256_file(runner),
        },
        "policy": {
            "starts_after_v4_stage_g_finalization": True,
            "same_all_110_inputs": True,
            "successful_results_overwritable": False,
            "automatic_protocol_fallback": False,
            "semantic_policy_frozen_before_v2_predictions": True,
        },
    }


def freeze_v2_comparison_manifest(path: str | Path, value: dict[str, Any]) -> None:
    output = Path(path)
    if output.exists():
        existing = json.loads(output.read_text(encoding="utf-8"))
        if existing != value:
            raise ValueError("V2 comparison manifest already exists with different content")
        return
    _atomic_json(output, value)


def load_v2_comparison_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA
        or manifest.get("status") != "frozen"
    ):
        raise ValueError("invalid V2 comparison manifest")
    for binding in (
        "config",
        "comparison_spec",
        "comparison_scorer",
        "comparison_finalizer",
        "annotations",
        "v4_common_baseline",
        "batch_runner",
    ):
        value = manifest[binding]
        if sha256_file(value["path"]) != value["sha256"]:
            raise ValueError(f"V2 comparison {binding} hash mismatch")
    input_list = manifest["input_list"]
    if sha256_file(input_list["path"]) != input_list["sha256"]:
        raise ValueError("V2 comparison input-list hash mismatch")
    if (
        sha256_file(manifest["v4_acceptance"]["manifest_path"])
        != manifest["v4_acceptance"]["manifest_sha256"]
        or sha256_file(
            manifest["v4_acceptance"]["finalization_manifest_path"]
        )
        != manifest["v4_acceptance"]["finalization_manifest_sha256"]
    ):
        raise ValueError("V4.1 evidence changed after V2 manifest freeze")
    manifest["_path"] = str(manifest_path)
    manifest["_sha256"] = sha256_file(manifest_path)
    return manifest


def _load_inputs(manifest: dict[str, Any]) -> list[dict[str, str]]:
    binding = manifest["input_list"]
    rows = json.loads(Path(binding["path"]).read_text(encoding="utf-8"))
    if not isinstance(rows, list) or len(rows) != binding["count"]:
        raise ValueError("invalid V2 comparison input list")
    seen: set[str] = set()
    normalized: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("V2 comparison input row must be an object")
        video_id = row.get("video_id")
        video_path = row.get("video_path")
        if (
            not isinstance(video_id, str)
            or video_id in seen
            or not isinstance(video_path, str)
            or not Path(video_path).is_file()
        ):
            raise ValueError("invalid V2 comparison input identity")
        seen.add(video_id)
        normalized.append({"video_id": video_id, "video_path": video_path})
    return normalized


def run_v2_comparison_batch(
    manifest_path: str | Path,
    output_dir: str | Path,
    *,
    retry_failed: bool = False,
    run_one_fn: Callable[..., dict[str, Any]] = run_one,
) -> dict[str, Any]:
    """Run or resume the frozen V2 comparison without overwriting success."""
    manifest = load_v2_comparison_manifest(manifest_path)
    inputs = _load_inputs(manifest)
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    expected_deployment = manifest["service_snapshot"]["deployment_manifest"]
    completed = skipped = failed = 0

    for item in inputs:
        video_id = item["video_id"]
        task_dir = root / video_id
        success_path = task_dir / "result.json"
        failure_path = task_dir / "failure.json"
        if success_path.exists():
            existing = json.loads(success_path.read_text(encoding="utf-8"))
            actual_deployment = (
                existing.get("runner_result", {})
                .get("runtime_identity", {})
                .get("visual_deployment", {})
                .get("deployment_manifest")
            )
            if (
                existing.get("v2_comparison_manifest_sha256")
                != manifest["_sha256"]
                or actual_deployment != expected_deployment
            ):
                raise ValueError(f"immutable V2 success identity mismatch: {video_id}")
            skipped += 1
            continue
        if failure_path.exists() and not retry_failed:
            failed += 1
            continue

        task_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(task_dir, 0o700)
        events_path = task_dir / "events.jsonl"

        def emit(event: dict[str, Any]) -> None:
            with events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")

        started_at = datetime.now(timezone.utc).isoformat()
        result = run_one_fn(
            item["video_path"],
            config_path=manifest["config"]["path"],
            video_id=video_id,
            event_callback=emit,
            work_dir=task_dir,
            question=manifest["question"],
            trace_task_id=f"{manifest['manifest_id']}:{video_id}",
        )
        record = {
            "schema_version": BATCH_SCHEMA,
            "v2_comparison_manifest_id": manifest["manifest_id"],
            "v2_comparison_manifest_sha256": manifest["_sha256"],
            "video_id": video_id,
            "video_path": item["video_path"],
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "runner_result": result,
        }
        actual_deployment = (
            result.get("runtime_identity", {})
            .get("visual_deployment", {})
            .get("deployment_manifest")
        )
        if result.get("ok") is True and actual_deployment == expected_deployment:
            _atomic_json(success_path, record)
            if failure_path.exists():
                failure_path.unlink()
            completed += 1
        else:
            if result.get("ok") is True:
                record["identity_error"] = "V2 deployment mismatch"
            _atomic_json(failure_path, record)
            failed += 1

    summary = {
        "schema_version": BATCH_SCHEMA,
        "v2_comparison_manifest_id": manifest["manifest_id"],
        "v2_comparison_manifest_sha256": manifest["_sha256"],
        "total": len(inputs),
        "completed_now": completed,
        "skipped_immutable_successes": skipped,
        "failed_or_pending_retry": failed,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_json(root / "batch_state.json", summary)
    return summary
