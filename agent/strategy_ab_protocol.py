"""Dataset and integrity helpers for the frozen Agent strategy experiment."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from agent.strategy_ab import DIAGNOSTIC_30_IDS, STRATEGY_AB_SCHEMA


def sha256_file(path: str | Path) -> str:
    """Return the SHA256 digest of one file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def load_split_ids(path: str | Path) -> tuple[str, ...]:
    """Load and validate a split JSON's unique video IDs."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    values = payload.get("video_ids")
    if not isinstance(values, list) or not values:
        raise ValueError(f"split has no video_ids: {path}")
    ids = tuple(str(item) for item in values)
    if len(ids) != len(set(ids)):
        raise ValueError(f"split contains duplicate video_ids: {path}")
    declared = payload.get("count")
    if declared is not None and declared != len(ids):
        raise ValueError(f"split count mismatch: {path}")
    return ids


def derive_protocol_sets(
    train_ids: tuple[str, ...],
    val_ids: tuple[str, ...],
    test_ids: tuple[str, ...],
) -> dict[str, list[str]]:
    """Derive the approved diagnostic, locked and descriptive subsets."""
    train, val, test = set(train_ids), set(val_ids), set(test_ids)
    if train & val or train & test or val & test:
        raise ValueError("fold0 train, val and test must be disjoint")
    all_ids = train | val | test
    diagnostic = set(DIAGNOSTIC_30_IDS)
    if len(all_ids) != 110:
        raise ValueError(f"expected 110 source videos, found {len(all_ids)}")
    if not diagnostic <= all_ids:
        missing = sorted(diagnostic - all_ids)
        raise ValueError(f"diagnostic30 is not contained in fold0: {missing}")
    locked = all_ids - diagnostic
    confirmatory = test - diagnostic
    if len(locked) != 80 or len(confirmatory) != 17:
        raise ValueError(
            f"unexpected derived sizes: locked={len(locked)}, confirmatory={len(confirmatory)}"
        )
    return {
        "fold0_train59": sorted(train),
        "fold0_validation30": sorted(val),
        "diagnostic30": sorted(diagnostic),
        "locked80": sorted(locked),
        "confirmatory_test17": sorted(confirmatory),
        "legacy_test21": sorted(test),
        "all110": sorted(all_ids),
    }


def build_protocol_manifest(
    *,
    splits_dir: str | Path,
    annotations_csv: str | Path,
    config_path: str | Path,
    videos_root: str | Path,
    frozen: bool = False,
) -> dict[str, Any]:
    """Build a hash-pinned manifest without marking the locked set as consumed."""
    splits = Path(splits_dir)
    paths = {
        "train": splits / "fold_0_train.json",
        "val": splits / "fold_0_val.json",
        "test": splits / "test.json",
    }
    sets = derive_protocol_sets(
        load_split_ids(paths["train"]),
        load_split_ids(paths["val"]),
        load_split_ids(paths["test"]),
    )
    inputs = {
        name: {
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
        }
        for name, path in {
            **paths,
            "annotations": Path(annotations_csv),
            "agent_config": Path(config_path),
        }.items()
    }
    from agent.runner import load_config

    effective_config = load_config(config_path)
    video_root = Path(videos_root)
    videos = {
        video_id: {
            "path": str((video_root / f"{video_id}.mp4").resolve()),
            "sha256": sha256_file(video_root / f"{video_id}.mp4"),
        }
        for video_id in sets["all110"]
    }
    source_root = Path(__file__).resolve().parent.parent
    protocol_sources = {
        str(path.relative_to(source_root)): sha256_file(path)
        for path in (
            source_root / "agent" / "iterative_agent.py",
            source_root / "agent" / "runner.py",
            source_root / "agent" / "scoring_v4_1.py",
            source_root / "agent" / "strategy_ab.py",
            source_root / "agent" / "strategy_ab_protocol.py",
            source_root / "agent" / "strategy_ab_scoring.py",
            source_root / "agent" / "v4_1_evidence.py",
            source_root / "agent" / "prompts.py",
            source_root / "agent" / "contract.py",
            source_root / "agent" / "contracts" / "tensile_vlm_v4_1.json",
            source_root / "scripts" / "prepare_strategy_ab.py",
            source_root / "scripts" / "run_strategy_ab.py",
            source_root / "scripts" / "score_strategy_ab.py",
        )
    }
    return {
        "schema_version": STRATEGY_AB_SCHEMA,
        "protocol_status": "frozen" if frozen else "development",
        "locked80_consumed": False,
        "matching": {
            "primary_comparison": "B_vs_C",
            "budget_unit": "logical_visual_request",
            "per_video_rule": "B_request_count_equals_C_request_count",
            "invalid_and_failed_requests_consume_budget": True,
            "strategy_a_is_efficiency_anchor_only": True,
        },
        "sets": sets,
        "inputs": inputs,
        "effective_config_sha256": _canonical_sha256(effective_config),
        "videos": videos,
        "protocol_sources": protocol_sources,
    }


def verify_manifest_inputs(manifest: dict[str, Any]) -> None:
    """Fail closed when a pinned protocol input changed or disappeared."""
    if manifest.get("schema_version") != STRATEGY_AB_SCHEMA:
        raise ValueError("unsupported strategy A/B manifest schema")
    for name, item in manifest.get("inputs", {}).items():
        path = Path(item["path"])
        if not path.is_file():
            raise ValueError(f"pinned input is missing: {name}: {path}")
        actual = sha256_file(path)
        if actual != item.get("sha256"):
            raise ValueError(f"pinned input hash mismatch: {name}")
    for video_id, item in manifest.get("videos", {}).items():
        path = Path(item["path"])
        if not path.is_file():
            raise ValueError(f"pinned video is missing: {video_id}: {path}")
        if sha256_file(path) != item.get("sha256"):
            raise ValueError(f"pinned video hash mismatch: {video_id}")
    source_root = Path(__file__).resolve().parent.parent
    for relative_path, expected_hash in manifest.get("protocol_sources", {}).items():
        path = source_root / relative_path
        if not path.is_file() or sha256_file(path) != expected_hash:
            raise ValueError(f"protocol source drift: {relative_path}")
    from agent.runner import load_config

    config_path = manifest.get("inputs", {}).get("agent_config", {}).get("path")
    if config_path and _canonical_sha256(load_config(config_path)) != manifest.get(
        "effective_config_sha256"
    ):
        raise ValueError("effective configuration drift")
    git_pin = manifest.get("git")
    if isinstance(git_pin, dict) and git_pin.get("commit"):
        actual_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=source_root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if actual_commit != git_pin["commit"]:
            raise ValueError("git commit drift")
        if manifest.get("protocol_status") == "frozen":
            dirty = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=source_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if dirty:
                raise ValueError("frozen protocol requires a clean worktree")
