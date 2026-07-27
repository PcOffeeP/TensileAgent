from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent.acceptance_batch import run_acceptance_batch


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_acceptance_batch_resumes_without_overwriting_success(tmp_path: Path) -> None:
    video = tmp_path / "video_0001.mp4"
    video.write_bytes(b"fixture")
    inputs = tmp_path / "all_110.json"
    inputs.write_text(
        json.dumps([{"video_id": "video_0001", "video_path": str(video)}]),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text("backend: {}\n", encoding="utf-8")
    deployment = {
        "contract_version": "tensile-vlm/v4.1",
        "contract_hash": "contract",
        "model_version": "model",
    }
    manifest = {
        "schema_version": "tensile-agent/acceptance-manifest/v1",
        "status": "frozen",
        "manifest_id": "fixture",
        "agent_runtime_commit": "a" * 40,
        "visual_contract_version": "tensile-vlm/v4.1",
        "service_deployment": {"deployment_manifest": deployment},
        "config": {"path": str(config), "sha256": _sha(config)},
        "question": "请完整分析",
        "input_lists": {
            "all_110": {
                "path": str(inputs),
                "sha256": _sha(inputs),
                "count": 1,
            }
        },
        "scoring": {"path": "spec.json", "sha256": "scorer"},
        "thresholds": {"has_fracture_accuracy": 0.85},
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    calls: list[str] = []

    def fake_run_one(path: str, **kwargs):
        calls.append(path)
        return {
            "ok": True,
            "result": {
                "schema_version": "tensile-agent/result/v4.1",
                "video_id": kwargs["video_id"],
                "status": "no_fracture",
                "has_fracture": False,
            },
            "runtime_identity": {
                "visual_deployment": {"deployment_manifest": deployment}
            },
        }

    output = tmp_path / "output"
    first = run_acceptance_batch(
        manifest_path,
        output,
        run_one_fn=fake_run_one,
    )
    success_bytes = (output / "video_0001" / "result.json").read_bytes()
    second = run_acceptance_batch(
        manifest_path,
        output,
        run_one_fn=fake_run_one,
    )

    assert first["completed_now"] == 1
    assert second["skipped_immutable_successes"] == 1
    assert calls == [str(video)]
    assert (output / "video_0001" / "result.json").read_bytes() == success_bytes
