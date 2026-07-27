"""Identity-bound, resumable batch execution for the V4.1 Agent acceptance."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from agent.runner import run_one


MANIFEST_SCHEMA = "tensile-agent/acceptance-manifest/v1"
BATCH_SCHEMA = "tensile-agent/acceptance-batch/v1"
STAGE_G_AUTHORIZATION_SCHEMA = "tensile-agent/stage-g-authorization/v1"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_acceptance_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path).resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise ValueError("unsupported acceptance manifest schema")
    if manifest.get("status") != "frozen":
        raise ValueError("acceptance manifest must be frozen")
    if manifest.get("visual_contract_version") != "tensile-vlm/v4.1":
        raise ValueError("acceptance manifest must pin tensile-vlm/v4.1")
    for key in (
        "manifest_id",
        "agent_runtime_commit",
        "service_deployment",
        "config",
        "question",
        "input_lists",
        "scoring",
        "thresholds",
    ):
        if key not in manifest:
            raise ValueError(f"acceptance manifest missing {key}")
    manifest["_path"] = str(manifest_path)
    manifest["_sha256"] = sha256_file(manifest_path)
    return manifest


def load_bound_input_list(
    manifest: dict[str, Any],
    list_name: str,
) -> list[dict[str, str]]:
    try:
        binding = manifest["input_lists"][list_name]
    except KeyError as exc:
        raise ValueError(f"unknown input list {list_name}") from exc
    path = Path(binding["path"])
    if not path.is_absolute():
        path = Path(manifest["_path"]).parent / path
    path = path.resolve()
    if sha256_file(path) != binding["sha256"]:
        raise ValueError(f"input list hash mismatch: {list_name}")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or len(rows) != binding["count"]:
        raise ValueError(f"input list count mismatch: {list_name}")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("input rows must be objects")
        video_id = row.get("video_id")
        video_path = row.get("video_path")
        if not isinstance(video_id, str) or not video_id.strip():
            raise ValueError("input row has invalid video_id")
        if video_id in seen:
            raise ValueError(f"duplicate video_id: {video_id}")
        if not isinstance(video_path, str) or not Path(video_path).is_file():
            raise ValueError(f"input video is unavailable: {video_id}")
        seen.add(video_id)
        normalized.append({"video_id": video_id, "video_path": video_path})
    return normalized


def _deployment_matches(result: dict[str, Any], expected: dict[str, Any]) -> bool:
    actual = (
        result.get("runtime_identity", {})
        .get("visual_deployment", {})
        .get("deployment_manifest")
    )
    return actual == expected


def load_stage_g_authorization(
    path: str | Path,
    manifest: dict[str, Any],
    list_name: str,
) -> dict[str, Any]:
    """Validate the one-time authorization required for semantic held-out runs."""
    authorization_path = Path(path).resolve()
    authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
    if authorization.get("schema_version") != STAGE_G_AUTHORIZATION_SCHEMA:
        raise ValueError("unsupported Stage G authorization schema")
    if authorization.get("status") != "authorized":
        raise ValueError("Stage G authorization is not active")
    if authorization.get("agent_acceptance_manifest_id") != manifest["manifest_id"]:
        raise ValueError("Stage G authorization manifest ID mismatch")
    if authorization.get("agent_acceptance_manifest_sha256") != manifest["_sha256"]:
        raise ValueError("Stage G authorization manifest hash mismatch")
    if list_name not in authorization.get("allowed_input_lists", []):
        raise ValueError(f"Stage G authorization does not allow {list_name}")
    if authorization.get("heldout_semantics_opened") is not False:
        raise ValueError("Stage G authorization must be created before semantic opening")
    run_id = authorization.get("one_time_run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("Stage G authorization missing one_time_run_id")
    authorization["_path"] = str(authorization_path)
    authorization["_sha256"] = sha256_file(authorization_path)
    return authorization


def run_acceptance_batch(
    manifest_path: str | Path,
    output_dir: str | Path,
    *,
    list_name: str = "all_110",
    retry_failed: bool = False,
    stage_g_authorization_path: str | Path | None = None,
    run_one_fn: Callable[..., dict[str, Any]] = run_one,
) -> dict[str, Any]:
    """Run or resume one frozen input list without overwriting successes."""
    manifest = load_acceptance_manifest(manifest_path)
    protected_lists = {"all_110", "heldout_21"}
    stage_g_authorization: dict[str, Any] | None = None
    if (
        list_name in protected_lists
        and manifest.get("policy", {}).get(
            "heldout_semantic_runs_allowed_before_stage_g",
            False,
        )
        is False
    ):
        if stage_g_authorization_path is None:
            raise ValueError(
                f"{list_name} requires a frozen Stage G authorization"
            )
        stage_g_authorization = load_stage_g_authorization(
            stage_g_authorization_path,
            manifest,
            list_name,
        )
    inputs = load_bound_input_list(manifest, list_name)
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    config_path = Path(manifest["config"]["path"])
    if not config_path.is_absolute():
        config_path = Path(manifest["_path"]).parent / config_path
    if sha256_file(config_path) != manifest["config"]["sha256"]:
        raise ValueError("acceptance config hash mismatch")

    completed = skipped = failed = 0
    expected_deployment = manifest["service_deployment"]["deployment_manifest"]
    for item in inputs:
        video_id = item["video_id"]
        task_dir = root / video_id
        success_path = task_dir / "result.json"
        failure_path = task_dir / "failure.json"
        if success_path.exists():
            existing = json.loads(success_path.read_text(encoding="utf-8"))
            if (
                existing.get("acceptance_manifest_sha256") != manifest["_sha256"]
                or not _deployment_matches(existing["runner_result"], expected_deployment)
            ):
                raise ValueError(f"immutable success identity mismatch: {video_id}")
            skipped += 1
            continue
        if failure_path.exists() and not retry_failed:
            failed += 1
            continue

        task_dir.mkdir(parents=True, exist_ok=True)
        events_path = task_dir / "events.jsonl"

        def emit(event: dict[str, Any]) -> None:
            with events_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, ensure_ascii=False) + "\n")

        started_at = datetime.now(timezone.utc).isoformat()
        result = run_one_fn(
            item["video_path"],
            config_path=config_path,
            video_id=video_id,
            event_callback=emit,
            work_dir=task_dir,
            question=manifest["question"],
            trace_task_id=f"{manifest['manifest_id']}:{video_id}",
        )
        record = {
            "schema_version": BATCH_SCHEMA,
            "acceptance_manifest_id": manifest["manifest_id"],
            "acceptance_manifest_sha256": manifest["_sha256"],
            "stage_g_authorization_id": (
                stage_g_authorization.get("authorization_id")
                if stage_g_authorization is not None
                else None
            ),
            "stage_g_authorization_sha256": (
                stage_g_authorization.get("_sha256")
                if stage_g_authorization is not None
                else None
            ),
            "input_list": list_name,
            "video_id": video_id,
            "video_path": item["video_path"],
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "runner_result": result,
        }
        if result.get("ok") is True:
            if not _deployment_matches(result, expected_deployment):
                record["identity_error"] = "visual deployment does not match frozen manifest"
                _atomic_json(failure_path, record)
                failed += 1
                continue
            _atomic_json(success_path, record)
            if failure_path.exists():
                failure_path.unlink()
            completed += 1
        else:
            _atomic_json(failure_path, record)
            failed += 1

    summary = {
        "schema_version": BATCH_SCHEMA,
        "acceptance_manifest_id": manifest["manifest_id"],
        "acceptance_manifest_sha256": manifest["_sha256"],
        "stage_g_authorization_id": (
            stage_g_authorization.get("authorization_id")
            if stage_g_authorization is not None
            else None
        ),
        "stage_g_authorization_sha256": (
            stage_g_authorization.get("_sha256")
            if stage_g_authorization is not None
            else None
        ),
        "input_list": list_name,
        "total": len(inputs),
        "completed_now": completed,
        "skipped_immutable_successes": skipped,
        "failed_or_pending_retry": failed,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_json(root / "batch_state.json", summary)
    return summary
