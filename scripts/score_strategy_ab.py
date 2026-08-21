#!/usr/bin/env python3
"""Score completed A/B/C strategy results and emit paired comparisons."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from agent.scoring_v4_1 import normalize_ground_truth
from agent.strategy_ab import STRATEGY_AB_SCHEMA
from agent.strategy_ab_protocol import sha256_file, verify_manifest_inputs
from agent.strategy_ab_scoring import (
    paired_bootstrap_delta,
    presence_correct,
    score_method,
    time_within_1s,
)


def _load_annotations(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            video_id = str(row.get("video_id") or row.get("id") or "").strip()
            if not video_id:
                raise ValueError("annotation row is missing video ID")
            if video_id in rows:
                raise ValueError(f"duplicate annotation: {video_id}")
            row["video_id"] = video_id
            rows[video_id] = row
    return rows


def _validate_payload(
    payload: dict[str, Any],
    *,
    manifest_sha256: str,
    source_set: str,
    video_id: str,
    visual_identity: dict[str, Any],
    decision_identity: dict[str, Any],
) -> int:
    """Validate provenance and exact A/B/C request cardinalities."""
    if payload.get("schema_version") != STRATEGY_AB_SCHEMA:
        raise ValueError(f"result schema mismatch: {video_id}")
    if payload.get("manifest_sha256") != manifest_sha256:
        raise ValueError(f"result manifest mismatch: {video_id}")
    if payload.get("set") != source_set or payload.get("video_id") != video_id:
        raise ValueError(f"result identity mismatch: {video_id}")
    if payload.get("status") != "complete":
        raise ValueError(f"incomplete result: {video_id}")
    if payload.get("visual_deployment") != visual_identity:
        raise ValueError(f"visual deployment mismatch: {video_id}")
    if payload.get("decision_model") != decision_identity:
        raise ValueError(f"decision model mismatch: {video_id}")
    budget = payload.get("matched_budget")
    a = payload.get("strategy_a") or {}
    b = payload.get("strategy_b") or {}
    c = payload.get("strategy_c") or {}
    c_history = c.get("evaluation_trace", {}).get("history", [])
    if a.get("request_count") != 1 or len(a.get("rounds", [])) != 1:
        raise ValueError(f"A request mismatch: {video_id}")
    if (
        not isinstance(budget, int)
        or b.get("request_count") != budget
        or len(b.get("rounds", [])) != budget
        or c.get("evaluation_trace", {}).get("rounds") != budget
        or len(c_history) != budget
    ):
        raise ValueError(f"B/C budget mismatch: {video_id}")
    c_runtime = c.get("runtime_identity", {})
    if c_runtime.get("visual_deployment") != visual_identity:
        raise ValueError(f"C visual deployment mismatch: {video_id}")
    expected_c_decision = {
        key: decision_identity.get(key) for key in ("backend", "model", "digest")
    }
    if c_runtime.get("decision_model") != expected_c_decision:
        raise ValueError(f"C decision model mismatch: {video_id}")
    return budget


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--set",
        required=True,
        choices=(
            "diagnostic30",
            "locked80",
            "confirmatory_test17",
            "legacy_test21",
            "all110",
        ),
    )
    parser.add_argument("--results-root", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--bootstrap-iterations", type=int, default=10000)
    args = parser.parse_args()
    if args.bootstrap_iterations < 100:
        raise SystemExit("--bootstrap-iterations must be at least 100")

    manifest_path = Path(args.manifest)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_sha256 = sha256_file(manifest_path)
    verify_manifest_inputs(manifest)
    annotations = _load_annotations(Path(manifest["inputs"]["annotations"]["path"]))
    records: dict[str, list[tuple[dict[str, Any], dict[str, Any], int]]] = {
        "A": [],
        "B": [],
        "C": [],
    }
    request_quality = {
        method: {"logical_requests": 0, "valid_responses": 0, "invalid_or_failed": 0}
        for method in ("A", "B", "C")
    }
    records_by_id: dict[str, dict[str, tuple[dict[str, Any], dict[str, Any], int]]] = {}
    results_root = Path(args.results_root)
    for video_id in manifest["sets"][args.set]:
        candidate_sets = [args.set]
        if video_id in manifest["sets"]["locked80"]:
            candidate_sets.append("locked80")
        if video_id in manifest["sets"]["diagnostic30"]:
            candidate_sets.append("diagnostic30")
        paths = [
            results_root / set_name / video_id / "result.json"
            for set_name in dict.fromkeys(candidate_sets)
        ]
        path = next((item for item in paths if item.is_file()), paths[0])
        if not path.is_file():
            raise ValueError(f"missing result: {video_id}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        source_set = path.parent.parent.name
        visual_identity = json.loads(
            (results_root / source_set / "VISUAL_DEPLOYMENT.json").read_text(
                encoding="utf-8"
            )
        )
        decision_identity = json.loads(
            (results_root / source_set / "DECISION_MODEL.json").read_text(
                encoding="utf-8"
            )
        )
        truth = normalize_ground_truth(annotations[video_id])
        budget = _validate_payload(
            payload,
            manifest_sha256=manifest_sha256,
            source_set=source_set,
            video_id=video_id,
            visual_identity=visual_identity,
            decision_identity=decision_identity,
        )
        c_history = payload["strategy_c"].get("evaluation_trace", {}).get("history", [])
        if not isinstance(c_history, list) or len(c_history) != budget:
            raise ValueError(f"C trace/budget mismatch: {video_id}")
        method_rounds = {
            "A": payload["strategy_a"]["rounds"],
            "B": payload["strategy_b"]["rounds"],
            "C": [entry.get("result", {}) for entry in c_history],
        }
        for method, rounds in method_rounds.items():
            request_quality[method]["logical_requests"] += len(rounds)
            valid = sum(
                item.get("ok") is True and item.get("validation_error") is None
                for item in rounds
            )
            request_quality[method]["valid_responses"] += valid
            request_quality[method]["invalid_or_failed"] += len(rounds) - valid
        item_a = (truth, payload["strategy_a"]["prediction"], 1)
        item_b = (truth, payload["strategy_b"]["prediction"], budget)
        item_c = (truth, payload["strategy_c"]["result"], budget)
        records["A"].append(item_a)
        records["B"].append(item_b)
        records["C"].append(item_c)
        records_by_id[video_id] = {"A": item_a, "B": item_b, "C": item_c}

    paired_ids = [
        video_id
        for video_id, item in records_by_id.items()
        if item["B"][0].get("special_case") is None
    ]
    paired_b = [records_by_id[video_id]["B"] for video_id in paired_ids]
    paired_c = [records_by_id[video_id]["C"] for video_id in paired_ids]
    presence_differences = [
        presence_correct(item["B"][0], item["B"][1])
        - presence_correct(item["C"][0], item["C"][1])
        for video_id in paired_ids
        for item in [records_by_id[video_id]]
    ]
    positive_b = [
        item
        for item in records["B"]
        if item[0]["has_fracture"] is True
        and isinstance(item[0].get("fracture_time"), (int, float))
    ]
    positive_c = [
        item
        for item in records["C"]
        if item[0]["has_fracture"] is True
        and isinstance(item[0].get("fracture_time"), (int, float))
    ]
    subgroup_dimensions: dict[str, dict[str, list[str]]] = {
        "fold0_source_split": {
            "train": manifest["sets"]["fold0_train59"],
            "validation": manifest["sets"]["fold0_validation30"],
            "test": manifest["sets"]["legacy_test21"],
        }
    }
    for dimension, column in (
        ("fracture_mode", "断裂模式"),
        ("material", "材料类型"),
        ("clarity", "清晰度"),
        ("location", "断裂位置"),
    ):
        groups: dict[str, list[str]] = {}
        for video_id in manifest["sets"][args.set]:
            value = str(annotations[video_id].get(column) or "missing").strip()
            groups.setdefault(value, []).append(video_id)
        subgroup_dimensions[dimension] = groups
    subgroup_reports: dict[str, Any] = {}
    selected_ids = set(manifest["sets"][args.set])
    for dimension, groups in subgroup_dimensions.items():
        subgroup_reports[dimension] = {}
        for value, ids in groups.items():
            members = sorted(selected_ids & set(ids))
            if not members:
                continue
            subgroup_reports[dimension][value] = {
                method: score_method(
                    [records_by_id[video_id][method] for video_id in members]
                )
                for method in ("A", "B", "C")
            }

    report = {
        "schema_version": manifest["schema_version"],
        "set": args.set,
        "claims": (
            "fixed-model closed-corpus strategy comparison; not an independent "
            "model-generalization estimate"
        ),
        "metrics": {name: score_method(values) for name, values in records.items()},
        "request_quality": request_quality,
        "paired_b_vs_c": {
            "presence_wins_ties_losses_for_b": {
                "wins": sum(value > 0 for value in presence_differences),
                "ties": sum(value == 0 for value in presence_differences),
                "losses": sum(value < 0 for value in presence_differences),
            },
            "presence_accuracy_excluding_special_cases": paired_bootstrap_delta(
                paired_b,
                paired_c,
                score=presence_correct,
                iterations=args.bootstrap_iterations,
            ),
            "positive_time_within_1s": paired_bootstrap_delta(
                positive_b,
                positive_c,
                score=time_within_1s,
                iterations=args.bootstrap_iterations,
            ),
        },
        "subgroups_descriptive_only": subgroup_reports,
    }
    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"refusing to overwrite report: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {output}")


if __name__ == "__main__":
    main()
