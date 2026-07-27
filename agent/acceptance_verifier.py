"""Post-run chain-integrity verification for the frozen V4.1 acceptance."""

from __future__ import annotations

import json
import math
import stat
from pathlib import Path
from typing import Any

from agent.acceptance_batch import (
    load_acceptance_manifest,
    load_bound_input_list,
    load_stage_g_authorization,
)


RESULT_SCHEMA = "tensile-agent/result/v4.1"


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _read_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_no, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSONL") from exc
        if not isinstance(event, dict):
            raise ValueError(f"{path}:{line_no}: event must be an object")
        events.append(event)
    return events


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _strictly_increasing(values: list[float]) -> bool:
    return bool(values) and all(
        math.isfinite(value)
        and (index == 0 or value > values[index - 1])
        for index, value in enumerate(values)
    )


def _non_decreasing(values: list[float]) -> bool:
    return bool(values) and all(
        math.isfinite(value)
        and (index == 0 or value >= values[index - 1])
        for index, value in enumerate(values)
    )


def _diagnostic_error(
    path: Path,
    expected_deployment: dict[str, Any],
    seen_request_ids: set[str],
) -> str | None:
    diagnostic = _read_json(path)
    manifest = diagnostic.get("temp_video_manifest")
    if not isinstance(manifest, list) or not manifest:
        return "missing temp_video_manifest"
    original_times = [
        row.get("timestamp") for row in manifest if isinstance(row, dict)
    ]
    clip_times = [
        row.get("clip_timestamp") for row in manifest if isinstance(row, dict)
    ]
    if (
        len(original_times) != len(manifest)
        or not all(isinstance(value, (int, float)) for value in original_times)
        or not _non_decreasing([float(value) for value in original_times])
    ):
        return "invalid original-video timestamp mapping"
    if (
        len(clip_times) != len(manifest)
        or not all(isinstance(value, (int, float)) for value in clip_times)
        or not _strictly_increasing([float(value) for value in clip_times])
    ):
        return "invalid temporary-clip timestamp mapping"
    if not isinstance(diagnostic.get("temp_video_hash"), str):
        return "missing temp_video_hash"
    if not isinstance(diagnostic.get("temp_video_bytes"), int):
        return "missing temp_video_bytes"

    # Failed model calls remain auditable but do not carry usable semantics.
    if diagnostic.get("error") is not None:
        return None

    request_id = diagnostic.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        return "missing request_id"
    if request_id in seen_request_ids:
        return "duplicate request_id"
    seen_request_ids.add(request_id)
    if diagnostic.get("deployment_manifest") != expected_deployment:
        return "deployment identity mismatch"
    frames = diagnostic.get("sampled_frames")
    if not isinstance(frames, list) or not frames:
        return "missing sampled_frames"
    frame_times = [
        row.get("timestamp") for row in frames if isinstance(row, dict)
    ]
    if (
        len(frame_times) != len(frames)
        or not all(isinstance(value, (int, float)) for value in frame_times)
        or not _strictly_increasing([float(value) for value in frame_times])
    ):
        return "invalid sampled frame timestamps"
    max_frames = diagnostic.get("max_frames")
    if not isinstance(max_frames, int) or len(frames) > max_frames:
        return "sampled frame count exceeds max_frames"
    if diagnostic.get("mime_type") != "video/mp4":
        return "invalid MIME type"
    if not isinstance(diagnostic.get("base64_length"), int):
        return "missing base64_length"
    if not isinstance(diagnostic.get("raw_http_response"), dict):
        return "missing raw HTTP response"
    return None


def verify_acceptance_run(
    manifest_path: str | Path,
    authorization_path: str | Path,
    results_root: str | Path,
) -> dict[str, Any]:
    """Verify one complete all_110 run without producing semantic metrics."""
    manifest = load_acceptance_manifest(manifest_path)
    authorization = load_stage_g_authorization(
        authorization_path,
        manifest,
        "all_110",
    )
    inputs = load_bound_input_list(manifest, "all_110")
    root = Path(results_root).resolve()

    # Fail before reading any semantic result unless the one-time run is complete.
    expected_ids = {row["video_id"] for row in inputs}
    result_ids = {
        path.parent.name for path in root.glob("*/result.json") if path.is_file()
    }
    failure_ids = {
        path.parent.name for path in root.glob("*/failure.json") if path.is_file()
    }
    if result_ids != expected_ids or failure_ids:
        raise ValueError(
            "acceptance run is incomplete: "
            f"results={len(result_ids)}/{len(expected_ids)}, "
            f"failures={len(failure_ids)}"
        )

    expected_deployment = manifest["service_deployment"]["deployment_manifest"]
    input_by_id = {row["video_id"]: row for row in inputs}
    seen_request_ids: set[str] = set()
    recovery_path = root.parent / "recovery/recovery_completion.json"
    recovery_manifest_path = root.parent / "recovery/recovery_manifest.json"
    recovered_ids: set[str] = set()
    interrupted_pending_retry_allowed = False
    if recovery_path.is_file():
        recovery = _read_json(recovery_path)
        if (
            recovery.get("run_id") != authorization["one_time_run_id"]
            or recovery.get("recovered") is not True
            or recovery.get("failure_removed_after_success") is not True
            or recovery.get("source_clip_sha256_unchanged") is not True
            or recovery.get("semantic_identity_changed") is not False
        ):
            raise ValueError("invalid infrastructure recovery completion")
        recovered_video_id = recovery.get("video_id")
        if not isinstance(recovered_video_id, str):
            raise ValueError("recovery completion missing video_id")
        recovered_ids.add(recovered_video_id)
    if recovery_manifest_path.is_file():
        recovery_manifest = _read_json(recovery_manifest_path)
        if (
            recovery_manifest.get("run_id")
            != authorization["one_time_run_id"]
            or recovery_manifest.get("semantic_identity_changed") is not False
        ):
            raise ValueError("invalid infrastructure recovery manifest")
        interrupted_pending_retry_allowed = (
            recovery_manifest.get("retry_policy")
            == "retry_failed_and_continue_pending_same_one_time_run"
        )
    errors: dict[str, list[str]] = {}
    total_diagnostics = 0
    total_semantic_calls = 0
    total_events = 0
    total_evidence_calls = 0
    seen_evidence_request_ids: set[str] = set()

    for video_id in sorted(expected_ids):
        task_dir = root / video_id
        task_errors: list[str] = []
        record_path = task_dir / "result.json"
        events_path = task_dir / "events.jsonl"
        if _mode(task_dir) != 0o700:
            task_errors.append("task directory mode is not 0700")
        if _mode(record_path) != 0o600:
            task_errors.append("result mode is not 0600")
        if not events_path.is_file() or _mode(events_path) != 0o600:
            task_errors.append("events missing or mode is not 0600")

        record = _read_json(record_path)
        expected_input = input_by_id[video_id]
        if record.get("acceptance_manifest_id") != manifest["manifest_id"]:
            task_errors.append("acceptance manifest ID mismatch")
        if (
            record.get("acceptance_manifest_sha256")
            != manifest["_sha256"]
        ):
            task_errors.append("acceptance manifest hash mismatch")
        if (
            record.get("stage_g_authorization_id")
            != authorization["authorization_id"]
        ):
            task_errors.append("Stage G authorization ID mismatch")
        if (
            record.get("stage_g_authorization_sha256")
            != authorization["_sha256"]
        ):
            task_errors.append("Stage G authorization hash mismatch")
        if record.get("input_list") != "all_110":
            task_errors.append("input list mismatch")
        if (
            record.get("video_id") != video_id
            or record.get("video_path") != expected_input["video_path"]
        ):
            task_errors.append("input identity mismatch")

        runner = record.get("runner_result")
        if not isinstance(runner, dict) or runner.get("ok") is not True:
            task_errors.append("runner did not succeed")
            runner = {}
        visual = (
            runner.get("runtime_identity", {})
            .get("visual_deployment", {})
        )
        if visual.get("contract_version") != "tensile-vlm/v4.1":
            task_errors.append("visual contract version mismatch")
        if visual.get("deployment_manifest") != expected_deployment:
            task_errors.append("visual deployment mismatch")
        result = runner.get("result")
        if not isinstance(result, dict):
            task_errors.append("missing public result")
            result = {}
        if (
            result.get("schema_version") != RESULT_SCHEMA
            or result.get("video_id") != video_id
        ):
            task_errors.append("public result identity mismatch")
        status = result.get("status")
        expected_has_fracture = {
            "fracture": True,
            "no_fracture": False,
            "unrecognized": None,
        }.get(status, "invalid")
        if (
            expected_has_fracture == "invalid"
            or result.get("has_fracture") is not expected_has_fracture
        ):
            task_errors.append("status/has_fracture mismatch")

        events = _read_events(events_path)
        total_events += len(events)
        start_indices = [
            index
            for index, event in enumerate(events)
            if event.get("event_type") == "video_started"
        ]
        if not start_indices:
            task_errors.append("video_started count mismatch")
            active_events = events
            historical_events: list[dict[str, Any]] = []
        else:
            active_events = events[start_indices[-1] :]
            historical_events = events[: start_indices[-1]]
        event_types = [event.get("event_type") for event in active_events]
        if event_types.count("video_started") != 1:
            task_errors.append("active video_started count mismatch")
        if event_types.count("video_finished") != 1:
            task_errors.append("video_finished count mismatch")
        if "video_failed" in event_types:
            task_errors.append("video_failed present in successful task")
        if historical_events:
            if video_id not in recovered_ids:
                historical_types = [
                    event.get("event_type") for event in historical_events
                ]
                if not (
                    interrupted_pending_retry_allowed
                    and "video_finished" not in historical_types
                ):
                    task_errors.append("unbound historical retry events")
            elif not any(
                event.get("event_type") == "video_failed"
                for event in historical_events
            ):
                task_errors.append(
                    "recovery history does not contain video_failed"
                )
        if any(event.get("video_id") != video_id for event in events):
            task_errors.append("event video identity mismatch")
        started = event_types.count("sample_and_infer_started")
        finished = event_types.count("sample_and_infer_finished")
        if started == 0 or started != finished:
            task_errors.append("sample_and_infer event count mismatch")

        diagnostics_dir = task_dir / "data/08_runtime/diagnostics"
        diagnostics = sorted(
            diagnostics_dir.glob(f"{video_id}_round_*_diagnostics.json")
        )
        if len(diagnostics) != finished:
            task_errors.append("diagnostic/event count mismatch")
        task_requests: dict[str, str] = {}
        task_clips: dict[str, list[float]] = {}
        for path in diagnostics:
            if _mode(path) != 0o600:
                task_errors.append(f"{path.name}: mode is not 0600")
                continue
            diagnostic = _read_json(path)
            if diagnostic.get("error") is None:
                total_semantic_calls += 1
            error = _diagnostic_error(
                path,
                expected_deployment,
                seen_request_ids,
            )
            if error:
                task_errors.append(f"{path.name}: {error}")
            elif diagnostic.get("error") is None:
                task_requests[str(diagnostic["request_id"])] = str(
                    diagnostic["temp_video_hash"]
                )
                task_clips[str(diagnostic["temp_video_hash"])] = [
                    float(frame["timestamp"])
                    for frame in diagnostic["sampled_frames"]
                ]
        total_diagnostics += len(diagnostics)

        summary_path = (
            diagnostics_dir / f"{video_id}_diagnostics_summary.json"
        )
        if not summary_path.is_file() or _mode(summary_path) != 0o600:
            task_errors.append("diagnostics summary missing or not 0600")
        else:
            summary = _read_json(summary_path)
            for entry in summary.get("history", []):
                internal = entry.get("result", {})
                model_output = internal.get("model_output", {})
                if (
                    model_output.get("clip_state") == "无法判断"
                    and internal.get("v4_1_search_direction") is not None
                ):
                    task_errors.append(
                        "无法判断 round produced a search direction"
                    )

        evidence = result.get("visual_evidence")
        if not isinstance(evidence, dict):
            task_errors.append("missing visual evidence envelope")
        elif evidence.get("status") == "available":
            references = evidence.get("references")
            if not isinstance(references, list) or not references:
                task_errors.append("available evidence has no references")
            else:
                for reference in references:
                    if not isinstance(reference, dict):
                        task_errors.append("invalid evidence reference")
                        continue
                    request_id = reference.get("request_id")
                    clip_hash = reference.get("clip_hash")
                    frame_timestamps = reference.get("frame_timestamps")
                    if not isinstance(request_id, str) or not request_id:
                        task_errors.append(
                            "evidence reference request_id is missing"
                        )
                    elif request_id in seen_evidence_request_ids:
                        task_errors.append(
                            "duplicate evidence request_id"
                        )
                    else:
                        seen_evidence_request_ids.add(request_id)
                        total_evidence_calls += 1
                    if clip_hash not in task_clips:
                        task_errors.append(
                            "evidence reference clip_hash is unbound"
                        )
                    elif (
                        not isinstance(frame_timestamps, list)
                        or [float(value) for value in frame_timestamps]
                        != task_clips[clip_hash]
                    ):
                        task_errors.append(
                            "evidence reference frame timestamps mismatch"
                        )
        elif status != "unrecognized":
            task_errors.append(
                "determinate result has no available visual evidence"
            )

        if task_errors:
            errors[video_id] = task_errors

    return {
        "schema_version": "tensile-agent/chain-integrity-report/v1",
        "acceptance_manifest_id": manifest["manifest_id"],
        "acceptance_manifest_sha256": manifest["_sha256"],
        "stage_g_authorization_id": authorization["authorization_id"],
        "stage_g_authorization_sha256": authorization["_sha256"],
        "input_list": "all_110",
        "expected_videos": len(expected_ids),
        "successful_videos": len(result_ids),
        "failed_videos": 0,
        "event_count": total_events,
        "diagnostic_count": total_diagnostics,
        "semantic_model_call_count": total_semantic_calls,
        "evidence_model_call_count": total_evidence_calls,
        "total_vlm_call_count": total_semantic_calls + total_evidence_calls,
        "unique_request_id_count": len(seen_request_ids),
        "unique_evidence_request_id_count": len(
            seen_evidence_request_ids
        ),
        "all_tasks_same_deployment": not any(
            "deployment" in error
            for task_errors in errors.values()
            for error in task_errors
        ),
        "protocol_mixing_count": sum(
            "contract version" in error
            for task_errors in errors.values()
            for error in task_errors
        ),
        "unrecognized_search_direction_count": sum(
            "search direction" in error
            for task_errors in errors.values()
            for error in task_errors
        ),
        "integrity_error_count": sum(map(len, errors.values())),
        "errors": errors,
        "passed": not errors,
    }
