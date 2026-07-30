#!/usr/bin/env python3
"""Prepare the frozen Agent strategy A/B protocol manifest."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from agent.strategy_ab_protocol import build_protocol_manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--splits-dir", required=True)
    parser.add_argument("--annotations", required=True)
    parser.add_argument("--videos-root", required=True)
    parser.add_argument("--config", default="agent/config.yaml")
    parser.add_argument(
        "--freeze",
        action="store_true",
        help="create the clean-repository manifest required for locked80",
    )
    parser.add_argument(
        "--output",
        default="data/08_runtime/strategy_ab/protocol.json",
    )
    args = parser.parse_args()

    if args.freeze:
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if dirty:
            raise SystemExit("refusing to freeze protocol from a dirty worktree")

    output = Path(args.output)
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing manifest: {output}")
    manifest = build_protocol_manifest(
        splits_dir=args.splits_dir,
        annotations_csv=args.annotations,
        config_path=args.config,
        videos_root=args.videos_root,
        frozen=args.freeze,
    )
    manifest["git"] = {
        "commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "worktree_clean": not bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {output}")
    for name, ids in manifest["sets"].items():
        print(f"{name}: {len(ids)}")


if __name__ == "__main__":
    main()
