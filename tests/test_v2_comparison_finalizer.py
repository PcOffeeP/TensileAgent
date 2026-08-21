import json
from pathlib import Path

from agent.acceptance_batch import sha256_file
from agent.v2_comparison_batch import build_v2_comparison_manifest
from agent.v2_comparison_finalizer import finalize_v2_comparison
from agent.v2_comparison_scoring import build_v4_common_baseline


def _write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_v2_comparison_finalizer_freezes_passing_common_gate(
    tmp_path: Path,
) -> None:
    videos = []
    for video_id in ("fracture", "negative", "special"):
        path = tmp_path / f"{video_id}.mp4"
        path.write_bytes(video_id.encode())
        videos.append({"video_id": video_id, "video_path": str(path)})
    inputs = tmp_path / "all.json"
    _write(inputs, videos)
    config = tmp_path / "v4.yaml"
    config.write_text("backend: {}\n", encoding="utf-8")
    v4_manifest_path = tmp_path / "v4_manifest.json"
    _write(
        v4_manifest_path,
        {
            "schema_version": "tensile-agent/acceptance-manifest/v1",
            "status": "frozen",
            "manifest_id": "v4",
            "agent_runtime_commit": "a" * 40,
            "visual_contract_version": "tensile-vlm/v4.1",
            "service_deployment": {"deployment_manifest": {}},
            "config": {"path": str(config), "sha256": sha256_file(config)},
            "question": "analyze",
            "input_lists": {
                "all_110": {
                    "path": str(inputs),
                    "sha256": sha256_file(inputs),
                    "count": 3,
                }
            },
            "scoring": {},
            "thresholds": {},
        },
    )
    annotations = tmp_path / "annotations.csv"
    annotations.write_text(
        "video_id,source_type,location_canonical,has_fracture,"
        "fracture_time,duration\n"
        "fracture,脆性断裂,inside_gauge,true,2,10\n"
        "negative,未断裂,,false,,10\n"
        "special,未夹紧,,,,10\n",
        encoding="utf-8",
    )
    finalization_path = tmp_path / "finalization_manifest.json"
    _write(
        finalization_path,
        {
            "schema_version": "tensile-agent/stage-g-finalization/v1",
            "status": "scored_awaiting_v2_comparison",
            "finalization_id": "final",
            "inputs": {
                "manifest_sha256": sha256_file(v4_manifest_path),
                "annotations_sha256": sha256_file(annotations),
            },
            "artifacts": {},
            "stage_g_gate": {
                "passed_before_v2_comparison": True,
                "final_acceptance_pending_v2_comparison": True,
            },
        },
    )
    v4_results = tmp_path / "v4_results"
    predictions = {
        "fracture": {
            "status": "fracture",
            "has_fracture": True,
            "time_range": [1.5, 2.5],
            "fracture_type": "脆性断裂",
            "location": "inside_gauge",
        },
        "negative": {
            "status": "no_fracture",
            "has_fracture": False,
        },
        "special": {
            "status": "unrecognized",
            "has_fracture": None,
            "special_case": "未夹紧",
        },
    }
    for video_id, prediction in predictions.items():
        task = v4_results / video_id
        task.mkdir(parents=True)
        _write(
            task / "result.json",
            {
                "acceptance_manifest_sha256": sha256_file(v4_manifest_path),
                "runner_result": {
                    "result": {
                        "schema_version": "tensile-agent/result/v4.1",
                        "video_id": video_id,
                        **prediction,
                    }
                },
            },
        )
    baseline = build_v4_common_baseline(
        v4_acceptance_manifest_path=v4_manifest_path,
        v4_finalization_manifest_path=finalization_path,
        annotations_path=annotations,
        results_root=v4_results,
    )
    baseline_path = tmp_path / "baseline.json"
    _write(baseline_path, baseline)

    v2_config = tmp_path / "v2.yaml"
    v2_config.write_text("backend: {}\n", encoding="utf-8")
    spec = tmp_path / "spec.json"
    _write(
        spec,
        {
            "schema_version": "tensile-agent/v2-comparison-spec/v1",
            "comparison_version": "v2-v4.1-common-metrics-v1",
            "regression_rule": {"absolute_tolerance": 0.03},
        },
    )
    scorer = tmp_path / "scorer.py"
    scorer.write_text("# frozen scorer\n", encoding="utf-8")
    finalizer = tmp_path / "finalizer.py"
    finalizer.write_text("# frozen finalizer\n", encoding="utf-8")
    runner = tmp_path / "runner.py"
    runner.write_text("# frozen runner\n", encoding="utf-8")
    deployment = {
        "contract_version": "tensile-vlm/v2",
        "model_version": "v2",
    }
    manifest = build_v2_comparison_manifest(
        v4_acceptance_manifest_path=v4_manifest_path,
        v4_finalization_manifest_path=finalization_path,
        config_path=v2_config,
        comparison_spec_path=spec,
        comparison_scorer_path=scorer,
        comparison_finalizer_path=finalizer,
        annotations_path=annotations,
        v4_common_baseline_path=baseline_path,
        service_snapshot={
            "contract_version": "tensile-vlm/v2",
            "deployment_manifest": deployment,
        },
        agent_runtime_commit="b" * 40,
        batch_runner_path=runner,
    )
    manifest_path = tmp_path / "v2_manifest.json"
    _write(manifest_path, manifest)
    manifest_hash = sha256_file(manifest_path)
    v2_results = tmp_path / "v2_results"
    for video_id, prediction in predictions.items():
        v2_prediction = dict(prediction)
        if video_id == "special":
            v2_prediction.pop("special_case")
            v2_prediction["unrecognized_reason"] = "not_clamped"
        task = v2_results / video_id
        task.mkdir(parents=True)
        _write(
            task / "result.json",
            {
                "v2_comparison_manifest_sha256": manifest_hash,
                "video_path": next(
                    row["video_path"] for row in videos if row["video_id"] == video_id
                ),
                "runner_result": {
                    "ok": True,
                    "runtime_identity": {
                        "visual_deployment": {"deployment_manifest": deployment}
                    },
                    "result": {
                        "schema_version": "tensile-agent/result/v2",
                        "video_id": video_id,
                        **v2_prediction,
                    },
                },
            },
        )
    report = finalize_v2_comparison(
        manifest_path,
        v2_results,
        tmp_path / "final",
    )
    assert report["final_gate"]["final_acceptance_passed"] is True
    assert (
        Path(report["output_dir"]) / "comparison_finalization_manifest.json"
    ).is_file()
