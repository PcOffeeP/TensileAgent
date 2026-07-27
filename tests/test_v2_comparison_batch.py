import json
from pathlib import Path

from agent.acceptance_batch import sha256_file
from agent.v2_comparison_batch import (
    build_v2_comparison_manifest,
    run_v2_comparison_batch,
)


DEPLOYMENT = {
    "contract_version": "tensile-vlm/v2",
    "model_version": "v2",
}


def _prepare(tmp_path: Path) -> tuple[dict, Path]:
    video = tmp_path / "v.mp4"
    video.write_bytes(b"video")
    inputs = tmp_path / "inputs.json"
    inputs.write_text(
        json.dumps([{"video_id": "v", "video_path": str(video)}]),
        encoding="utf-8",
    )
    config = tmp_path / "config.yaml"
    config.write_text("backend: {}\n", encoding="utf-8")
    spec = tmp_path / "spec.json"
    spec.write_text("{}\n", encoding="utf-8")
    scorer = tmp_path / "scorer.py"
    scorer.write_text("# scorer\n", encoding="utf-8")
    finalizer = tmp_path / "finalizer.py"
    finalizer.write_text("# finalizer\n", encoding="utf-8")
    annotations = tmp_path / "annotations.csv"
    annotations.write_text("video_id,type\nv,未断裂\n", encoding="utf-8")
    runner = tmp_path / "runner.py"
    runner.write_text("# runner\n", encoding="utf-8")
    v4 = tmp_path / "v4.json"
    v4.write_text(
        json.dumps(
            {
                "schema_version": "tensile-agent/acceptance-manifest/v1",
                "status": "frozen",
                "manifest_id": "v4",
                "question": "analyze",
                "input_lists": {
                    "all_110": {
                        "path": str(inputs),
                        "sha256": sha256_file(inputs),
                        "count": 1,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    final = tmp_path / "final.json"
    final.write_text(
        json.dumps(
            {
                "schema_version": "tensile-agent/stage-g-finalization/v1",
                "status": "scored_awaiting_v2_comparison",
                "finalization_id": "final",
                "stage_g_gate": {
                    "final_acceptance_pending_v2_comparison": True
                },
            }
        ),
        encoding="utf-8",
    )
    baseline = tmp_path / "v4_common_baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "schema_version": "tensile-agent/v4-common-baseline/v1",
                "v4_acceptance_manifest_sha256": sha256_file(v4),
                "v4_finalization_manifest_sha256": sha256_file(final),
                "annotations_sha256": sha256_file(annotations),
                "video_count": 1,
                "report": {},
            }
        ),
        encoding="utf-8",
    )
    manifest = build_v2_comparison_manifest(
        v4_acceptance_manifest_path=v4,
        v4_finalization_manifest_path=final,
        config_path=config,
        comparison_spec_path=spec,
        comparison_scorer_path=scorer,
        comparison_finalizer_path=finalizer,
        annotations_path=annotations,
        v4_common_baseline_path=baseline,
        service_snapshot={
            "contract_version": "tensile-vlm/v2",
            "deployment_manifest": DEPLOYMENT,
        },
        agent_runtime_commit="commit",
        batch_runner_path=runner,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest, manifest_path


def test_v2_batch_preserves_success_identity(tmp_path: Path) -> None:
    manifest, manifest_path = _prepare(tmp_path)

    def fake_run_one(*args, **kwargs):
        return {
            "ok": True,
            "runtime_identity": {
                "visual_deployment": {
                    "deployment_manifest": DEPLOYMENT,
                }
            },
            "result": {
                "schema_version": "tensile-agent/result/v2",
                "video_id": "v",
                "status": "no_fracture",
                "has_fracture": False,
            },
        }

    root = tmp_path / "results"
    first = run_v2_comparison_batch(
        manifest_path,
        root,
        run_one_fn=fake_run_one,
    )
    assert first["completed_now"] == 1
    second = run_v2_comparison_batch(
        manifest_path,
        root,
        run_one_fn=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("immutable success reran")
        ),
    )
    assert second["skipped_immutable_successes"] == 1
    record = json.loads((root / "v/result.json").read_text())
    assert record["v2_comparison_manifest_id"] == manifest["manifest_id"]
