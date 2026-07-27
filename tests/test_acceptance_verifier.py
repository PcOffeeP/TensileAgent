import json
import os
from pathlib import Path

import pytest

from agent.acceptance_batch import sha256_file
from agent.acceptance_verifier import verify_acceptance_run


DEPLOYMENT = {
    "model_version": "m",
    "adapter_version": "a",
    "base_model_version": "b",
    "processor_version": "p",
    "llamafactory_version": "l",
    "transformers_version": "t",
    "config_fingerprint": "f",
    "runtime_device": "cuda:0",
    "runtime_dtype": "bfloat16",
    "contract_version": "tensile-vlm/v4.1",
    "contract_hash": "h",
}


def _write_json(path: Path, value: object, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.chmod(path, mode)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    inputs = tmp_path / "inputs.json"
    _write_json(
        inputs,
        [{"video_id": "v", "video_path": str(video)}],
    )
    config = tmp_path / "config.yaml"
    config.write_text("backend: {}\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest_value = {
        "schema_version": "tensile-agent/acceptance-manifest/v1",
        "status": "frozen",
        "manifest_id": "manifest",
        "agent_runtime_commit": "commit",
        "visual_contract_version": "tensile-vlm/v4.1",
        "service_deployment": {"deployment_manifest": DEPLOYMENT},
        "config": {"path": str(config), "sha256": sha256_file(config)},
        "question": "analyze",
        "input_lists": {
            "all_110": {
                "path": str(inputs),
                "sha256": sha256_file(inputs),
                "count": 1,
            }
        },
        "scoring": {},
        "thresholds": {},
        "policy": {"heldout_semantic_runs_allowed_before_stage_g": False},
    }
    _write_json(manifest, manifest_value)
    authorization = tmp_path / "authorization.json"
    _write_json(
        authorization,
        {
            "schema_version": "tensile-agent/stage-g-authorization/v1",
            "status": "authorized",
            "authorization_id": "authorization",
            "agent_acceptance_manifest_id": "manifest",
            "agent_acceptance_manifest_sha256": sha256_file(manifest),
            "allowed_input_lists": ["all_110"],
            "heldout_semantics_opened": False,
            "one_time_run_id": "run",
        },
    )
    root = tmp_path / "results"
    task = root / "v"
    task.mkdir(parents=True)
    os.chmod(task, 0o700)
    diagnostic = {
        "request_id": "request",
        "processor_version": "processor",
        "max_frames": 4,
        "sampled_frames": [
            {"index": 0, "timestamp": 0.1},
            {"index": 1, "timestamp": 0.2},
        ],
        "deployment_manifest": DEPLOYMENT,
        "temp_video_manifest": [
            {
                "temp_index": 0,
                "clip_timestamp": 0.0,
                "original_frame": 0,
                "timestamp": 0.1,
            },
            {
                "temp_index": 1,
                "clip_timestamp": 0.1,
                "original_frame": 1,
                "timestamp": 0.2,
            },
        ],
        "internal_frame_range": None,
        "temp_video_hash": "clip",
        "temp_video_bytes": 10,
        "mime_type": "video/mp4",
        "base64_length": 20,
        "raw_http_response": {},
        "transport_retries": 0,
        "correction_retries": 0,
        "elapsed_seconds": 1.0,
        "error": None,
        "video_anomaly_kind": None,
    }
    diagnostics = task / "data/08_runtime/diagnostics"
    _write_json(diagnostics / "v_round_0000_diagnostics.json", diagnostic)
    _write_json(
        diagnostics / "v_diagnostics_summary.json",
        {
            "history": [
                {
                    "result": {
                        "model_output": {"clip_state": "未断裂"},
                        "v4_1_search_direction": "later",
                    }
                }
            ]
        },
    )
    events = [
        {"event_type": "video_started", "video_id": "v"},
        {
            "event_type": "sample_and_infer_started",
            "video_id": "v",
        },
        {
            "event_type": "sample_and_infer_finished",
            "video_id": "v",
        },
        {"event_type": "video_finished", "video_id": "v"},
    ]
    events_path = task / "events.jsonl"
    events_path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )
    os.chmod(events_path, 0o600)
    record = {
        "acceptance_manifest_id": "manifest",
        "acceptance_manifest_sha256": sha256_file(manifest),
        "stage_g_authorization_id": "authorization",
        "stage_g_authorization_sha256": sha256_file(authorization),
        "input_list": "all_110",
        "video_id": "v",
        "video_path": str(video),
        "runner_result": {
            "ok": True,
            "error": None,
            "runtime_identity": {
                "visual_deployment": {
                    "contract_version": "tensile-vlm/v4.1",
                    "deployment_manifest": DEPLOYMENT,
                }
            },
            "result": {
                "schema_version": "tensile-agent/result/v4.1",
                "video_id": "v",
                "status": "no_fracture",
                "has_fracture": False,
                "visual_evidence": {
                    "status": "available",
                    "references": [
                        {
                            "request_id": "evidence-request",
                            "clip_hash": "clip",
                            "frame_timestamps": [0.1, 0.2],
                        }
                    ],
                },
            },
        },
    }
    _write_json(task / "result.json", record)
    return manifest, authorization, root


def test_verify_complete_acceptance_run(tmp_path: Path) -> None:
    manifest, authorization, root = _fixture(tmp_path)
    report = verify_acceptance_run(manifest, authorization, root)
    assert report["passed"] is True
    assert report["successful_videos"] == 1
    assert report["semantic_model_call_count"] == 1
    assert report["evidence_model_call_count"] == 1
    assert report["total_vlm_call_count"] == 2


def test_incomplete_run_fails_before_reading_results(tmp_path: Path) -> None:
    manifest, authorization, root = _fixture(tmp_path)
    (root / "v/result.json").unlink()
    with pytest.raises(ValueError, match="run is incomplete"):
        verify_acceptance_run(manifest, authorization, root)


def test_unrecognized_round_must_not_set_direction(tmp_path: Path) -> None:
    manifest, authorization, root = _fixture(tmp_path)
    summary = (
        root
        / "v/data/08_runtime/diagnostics/v_diagnostics_summary.json"
    )
    _write_json(
        summary,
        {
            "history": [
                {
                    "result": {
                        "model_output": {"clip_state": "无法判断"},
                        "v4_1_search_direction": "later",
                    }
                }
            ]
        },
    )
    report = verify_acceptance_run(manifest, authorization, root)
    assert report["passed"] is False
    assert report["unrecognized_search_direction_count"] == 1


def test_bound_infrastructure_recovery_history_is_allowed(
    tmp_path: Path,
) -> None:
    manifest, authorization, root = _fixture(tmp_path)
    events_path = root / "v/events.jsonl"
    current = events_path.read_text(encoding="utf-8")
    historical = [
        {"event_type": "video_started", "video_id": "v"},
        {"event_type": "video_finished", "video_id": "v"},
        {"event_type": "video_failed", "video_id": "v"},
    ]
    events_path.write_text(
        "\n".join(json.dumps(event) for event in historical)
        + "\n"
        + current,
        encoding="utf-8",
    )
    _write_json(
        root.parent / "recovery/recovery_completion.json",
        {
            "run_id": "run",
            "video_id": "v",
            "recovered": True,
            "failure_removed_after_success": True,
            "source_clip_sha256_unchanged": True,
            "semantic_identity_changed": False,
        },
    )
    report = verify_acceptance_run(manifest, authorization, root)
    assert report["passed"] is True


def test_duplicate_original_timestamps_are_valid_monotonic_mapping(
    tmp_path: Path,
) -> None:
    manifest, authorization, root = _fixture(tmp_path)
    diagnostic_path = (
        root / "v/data/08_runtime/diagnostics/v_round_0000_diagnostics.json"
    )
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    diagnostic["temp_video_manifest"][1]["timestamp"] = 0.1
    _write_json(diagnostic_path, diagnostic)
    assert verify_acceptance_run(manifest, authorization, root)["passed"] is True


def test_interrupted_pending_task_history_is_bound_to_recovery_manifest(
    tmp_path: Path,
) -> None:
    manifest, authorization, root = _fixture(tmp_path)
    events_path = root / "v/events.jsonl"
    current = events_path.read_text(encoding="utf-8")
    interrupted = [
        {"event_type": "video_started", "video_id": "v"},
        {"event_type": "sample_and_infer_started", "video_id": "v"},
    ]
    events_path.write_text(
        "\n".join(json.dumps(event) for event in interrupted)
        + "\n"
        + current,
        encoding="utf-8",
    )
    _write_json(
        root.parent / "recovery/recovery_manifest.json",
        {
            "run_id": "run",
            "semantic_identity_changed": False,
            "retry_policy": "retry_failed_and_continue_pending_same_one_time_run",
        },
    )
    report = verify_acceptance_run(manifest, authorization, root)
    assert report["passed"] is True
