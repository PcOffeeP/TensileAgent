#!/usr/bin/env python3
"""Run the frozen A/B/C strategy experiment on the training machine."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from agent.config_util import get_active_model_config, get_local_model_digest
from agent.inference import _validate_preprocessing_meta
from agent.runner import (
    build_video_meta,
    create_clip_builder,
    create_inference_client,
    load_config,
    run_one,
)
from agent.strategy_ab import (
    STRATEGY_AB_SCHEMA,
    fixed_scan_ranges,
    map_single_call,
    reduce_fixed_scan,
)
from agent.strategy_ab_protocol import sha256_file, verify_manifest_inputs


LOCKED_ACK = "I_UNDERSTAND_LOCKED80_IS_ONE_TIME"


def _visual_round(
    *,
    video_path: Path,
    sample_range: list[float],
    inference_client: Any,
    clip_builder: Any,
) -> dict[str, Any]:
    """Execute one budget-consuming visual attempt and retain its outcome."""
    record: dict[str, Any] = {
        "ok": False,
        "sample_range": sample_range,
        "model_output": None,
        "validation_error": None,
    }
    try:
        clip = clip_builder.build_with_manifest(
            source_video=str(video_path),
            sample_range=sample_range,
        )
        result = inference_client.infer(clip)
        record["attempts"] = result.attempts
        pp_error_code = _validate_preprocessing_meta(
            result.preprocessing,
            getattr(inference_client, "deployment_snapshot", None),
        )
        if pp_error_code is not None:
            failure_code = (
                "deployment_drift"
                if pp_error_code
                in {
                    "deployment_drift",
                    "contract_version_mismatch",
                    "contract_hash_mismatch",
                }
                else "missing_or_invalid_preprocessing_metadata"
            )
            record["ok"] = False
            record["model_output"] = None
            record["infra_error"] = {
                "stage": "inference_transport",
                "code": failure_code,
                "message": f"服务端 preprocessing 元数据无效: {pp_error_code}",
            }
            if result.error is not None:
                record["validation_error"] = {
                    "code": result.error.code,
                    "message": result.error.message,
                    "field": result.error.field,
                }
            return record
        record["ok"] = result.ok
        record["model_output"] = result.model_output
        if result.error is not None:
            record["validation_error"] = {
                "code": result.error.code,
                "message": result.error.message,
                "field": result.error.field,
            }
    except Exception as exc:
        record["validation_error"] = {
            "code": type(exc).__name__,
            "message": str(exc),
            "field": None,
        }
    return record


def _atomic_write_new(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _guard_locked_run(
    manifest_path: Path, results_root: Path, acknowledgement: str | None
) -> None:
    marker = manifest_path.with_name("LOCKED80_STARTED.json")
    resolved_root = str(results_root.resolve())
    if marker.exists():
        existing = json.loads(marker.read_text(encoding="utf-8"))
        if existing.get("results_root") != resolved_root:
            raise SystemExit(
                "locked80 has already started with a different results root; "
                "new tuning or a second primary run is forbidden"
            )
        return
    if acknowledgement != LOCKED_ACK:
        raise SystemExit(f"locked80 requires --consume-locked80 {LOCKED_ACK}")
    _atomic_write_new(
        marker,
        {
            "schema_version": STRATEGY_AB_SCHEMA,
            "results_root": resolved_root,
            "warning": "Locked primary evaluation started. Do not tune after viewing results.",
        },
    )


def _pin_or_verify(path: Path, payload: dict[str, Any], label: str) -> None:
    """Pin a run identity once, then fail closed on drift."""
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != payload:
            raise RuntimeError(f"{label} drift")
        return
    _atomic_write_new(path, payload)


def _validate_existing_result(
    payload: dict[str, Any],
    *,
    manifest_sha256: str,
    set_name: str,
    video_id: str,
    visual_identity: dict[str, Any],
    decision_identity: dict[str, Any],
) -> None:
    """Reject stale, foreign or internally inconsistent resume artifacts."""
    if payload.get("schema_version") != STRATEGY_AB_SCHEMA:
        raise ValueError(f"result schema mismatch: {video_id}")
    if payload.get("manifest_sha256") != manifest_sha256:
        raise ValueError(f"result manifest mismatch: {video_id}")
    if payload.get("set") != set_name or payload.get("video_id") != video_id:
        raise ValueError(f"result identity mismatch: {video_id}")
    if payload.get("visual_deployment") != visual_identity:
        raise ValueError(f"result visual deployment mismatch: {video_id}")
    if payload.get("decision_model") != decision_identity:
        raise ValueError(f"result decision model mismatch: {video_id}")
    if payload.get("status") == "incomplete":
        return
    if payload.get("status") != "complete":
        raise ValueError(f"result status mismatch: {video_id}")
    budget = payload.get("matched_budget")
    a = payload.get("strategy_a") or {}
    b = payload.get("strategy_b") or {}
    c_history = (
        (payload.get("strategy_c") or {}).get("evaluation_trace", {}).get("history", [])
    )
    if a.get("request_count") != 1 or len(a.get("rounds", [])) != 1:
        raise ValueError(f"strategy A request mismatch: {video_id}")
    if (
        not isinstance(budget, int)
        or b.get("request_count") != budget
        or len(b.get("rounds", [])) != budget
        or len(c_history) != budget
    ):
        raise ValueError(f"strategy B/C request mismatch: {video_id}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--set",
        required=True,
        choices=("diagnostic30", "locked80"),
    )
    parser.add_argument("--videos-root", required=True)
    parser.add_argument("--results-root", required=True)
    parser.add_argument("--consume-locked80")
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_sha256 = sha256_file(manifest_path)
    verify_manifest_inputs(manifest)
    video_ids = manifest["sets"][args.set]
    results_root = Path(args.results_root) / args.set
    if args.set == "locked80":
        if manifest.get("protocol_status") != "frozen":
            raise SystemExit("locked80 requires a manifest created with --freeze")
        _guard_locked_run(manifest_path, results_root, args.consume_locked80)

    config_path = Path(manifest["inputs"]["agent_config"]["path"])
    config = load_config(config_path)
    decision_identity = get_active_model_config(config)
    if decision_identity.get("backend") == "local":
        decision_identity["digest"] = get_local_model_digest(
            str(decision_identity.get("model")),
            str(decision_identity.get("base_url")),
        )
        if not decision_identity["digest"]:
            raise RuntimeError("local decision model digest is unavailable")
    else:
        decision_identity["digest"] = None
    _pin_or_verify(
        results_root / "DECISION_MODEL.json",
        decision_identity,
        "decision model",
    )
    inference_client = create_inference_client(config)
    direct_identity = inference_client.preflight()
    _pin_or_verify(
        results_root / "VISUAL_DEPLOYMENT.json",
        direct_identity,
        "visual deployment",
    )
    clip_builder = create_clip_builder(
        config,
        output_dir=results_root / "_clips",
    )

    for video_id in video_ids:
        output_path = results_root / video_id / "result.json"
        if output_path.exists():
            _validate_existing_result(
                json.loads(output_path.read_text(encoding="utf-8")),
                manifest_sha256=manifest_sha256,
                set_name=args.set,
                video_id=video_id,
                visual_identity=direct_identity,
                decision_identity=decision_identity,
            )
            print(f"skip existing {video_id}")
            continue
        video_path = Path(manifest["videos"][video_id]["path"])
        requested_path = Path(args.videos_root) / f"{video_id}.mp4"
        if requested_path.resolve() != video_path.resolve():
            raise RuntimeError(
                f"--videos-root differs from pinned manifest: {video_id}"
            )
        meta = build_video_meta(video_path, video_id=video_id)
        duration = float(meta["duration"])

        strategy_c = run_one(
            video_path,
            config_path=config_path,
            video_id=video_id,
            work_dir=results_root / video_id / "agent_work",
            trace_task_id=f"strategy-ab-{args.set}-{video_id}",
            agent_config_snapshot=decision_identity,
            include_internal_trace=True,
        )
        trace = strategy_c.get("evaluation_trace") or {}
        budget = trace.get("rounds")
        if (
            strategy_c.get("ok") is not True
            or not isinstance(budget, int)
            or not 1 <= budget <= len(fixed_scan_ranges(duration))
        ):
            payload = {
                "schema_version": STRATEGY_AB_SCHEMA,
                "manifest_sha256": manifest_sha256,
                "set": args.set,
                "video_id": video_id,
                "duration": duration,
                "status": "incomplete",
                "reason": "strategy_c_failed_or_has_invalid_budget",
                "visual_deployment": direct_identity,
                "decision_model": decision_identity,
                "strategy_c": strategy_c,
            }
            _atomic_write_new(output_path, payload)
            print(f"incomplete {video_id}")
            continue

        c_identity = strategy_c.get("runtime_identity", {}).get("visual_deployment")
        if c_identity != direct_identity:
            raise RuntimeError(f"visual deployment drift before A/B calls: {video_id}")
        c_decision = strategy_c.get("runtime_identity", {}).get("decision_model") or {}
        expected_c_decision = {
            key: decision_identity.get(key) for key in ("backend", "model", "digest")
        }
        if c_decision != expected_c_decision:
            raise RuntimeError(f"decision model selection drift: {video_id}")

        ranges = fixed_scan_ranges(duration)
        a_round = _visual_round(
            video_path=video_path,
            sample_range=ranges[0],
            inference_client=inference_client,
            clip_builder=clip_builder,
        )
        b_rounds = [
            _visual_round(
                video_path=video_path,
                sample_range=sample_range,
                inference_client=inference_client,
                clip_builder=clip_builder,
            )
            for sample_range in ranges[:budget]
        ]
        payload = {
            "schema_version": STRATEGY_AB_SCHEMA,
            "manifest_sha256": manifest_sha256,
            "set": args.set,
            "video_id": video_id,
            "duration": duration,
            "status": "complete",
            "matched_budget": budget,
            "visual_deployment": direct_identity,
            "decision_model": decision_identity,
            "strategy_a": {
                "prediction": map_single_call(a_round),
                "rounds": [a_round],
                "request_count": 1,
            },
            "strategy_b": {
                "prediction": reduce_fixed_scan(
                    b_rounds,
                    duration=duration,
                    tolerance_seconds=float(
                        config.get("agent", {}).get("tolerance_seconds", 1.0)
                    ),
                ),
                "rounds": b_rounds,
                "request_count": len(b_rounds),
            },
            "strategy_c": strategy_c,
        }
        _atomic_write_new(output_path, payload)
        print(f"complete {video_id}: matched budget={budget}")


if __name__ == "__main__":
    main()
