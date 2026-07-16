"""CLI entry point for the iterative agent runner.

Usage:
    python3 -m agent.run --video data/01_videos/video_0001.mp4
    python3 -m agent.run --videos-dir data/01_videos --mock
    python3 -m agent.run --input-list data/01_videos/list.txt --mock
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from agent import runner


def _make_event_writer(run_id: str, events_dir: Path) -> Any:
    """Return a callback that writes agent events to ``events_dir/run_id/*.jsonl``."""
    run_dir = events_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    def write_event(event: dict[str, Any]) -> None:
        video_id = event.get("video_id", "unknown")
        path = run_dir / f"{video_id}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    return write_event


def _write_jsonl(results: dict[str, Any] | list[dict[str, Any]] | list[Any], output_path: Path) -> None:
    """Write one or more result dicts as JSON lines to ``output_path``.

    ``RunnerResult`` objects are serialized via ``.model_dump()``.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        if isinstance(results, list):
            for item in results:
                if hasattr(item, "model_dump"):
                    f.write(json.dumps(item.model_dump()) + "\n")
                else:
                    f.write(json.dumps(item) + "\n")
        else:
            if hasattr(results, "model_dump"):
                f.write(json.dumps(results.model_dump()) + "\n")
            else:
                f.write(json.dumps(results) + "\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python3 -m agent.run",
        description="Run the iterative agent on one or more videos.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--video", "-v",
        help="Path to a single video to process.",
    )
    source.add_argument(
        "--videos-dir", "-d",
        help="Directory containing .mp4 videos to process in batch.",
    )
    source.add_argument(
        "--input-list", "-l",
        help="Text file containing one video path per line.",
    )
    parser.add_argument(
        "--config", "-c",
        default="agent/config.yaml",
        help="Agent configuration file path. (default: agent/config.yaml)",
    )
    parser.add_argument(
        "--output", "-o",
        default="data/08_runtime/results/run.jsonl",
        help="Result output JSONL path. (default: data/08_runtime/results/run.jsonl)",
    )
    parser.add_argument(
        "--work-dir",
        default=".",
        help="Workspace root under which data/08_runtime is created. (default: current directory)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Enable mock inference mode (sets INFERENCE_MOCK=1).",
    )
    parser.add_argument("--agent-backend", choices=["remote", "local"], default=None,
                        help="Override agent backend (remote or local). Useful for quickly switching between models for comparison.")
    parser.add_argument("--agent-model", type=str, default=None,
                        help="Override agent model name. E.g. 'qwen-max', 'qwen3.5:7b'. Useful for testing different models.")
    parser.add_argument(
        "--question", "-q",
        default="请完整分析这段拉伸试验视频",
        help="Natural-language question about the video. It is parsed by the Agent and never forwarded to MiniCPM.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.mock:
        os.environ["INFERENCE_MOCK"] = "1"

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    work_dir = Path(args.work_dir)
    events_dir = work_dir / "data" / "08_runtime" / "events"
    output_path = Path(args.output)
    event_callback = _make_event_writer(run_id, events_dir)

    if args.video:
        result = runner.run_one(
            args.video,
            config_path=args.config,
            event_callback=event_callback,
            work_dir=work_dir,
            agent_backend=args.agent_backend,
            agent_model=args.agent_model,
            question=args.question,
        )
        if not result["ok"]:
            print(f"Run failed for {args.video}: {result['error']['message']}", file=sys.stderr)
            sys.exit(1)
        _write_jsonl(result, output_path)
        print(f"Result written to {output_path}")
        return

    # Batch mode.
    if args.videos_dir:
        video_dir = Path(args.videos_dir)
        video_paths = sorted(video_dir.glob("*.mp4"))
        if not video_paths:
            print(f"No .mp4 videos found in {video_dir}", file=sys.stderr)
            sys.exit(1)
    else:
        input_list_path = Path(args.input_list)
        if not input_list_path.is_file():
            print(f"Input list not found: {input_list_path}", file=sys.stderr)
            sys.exit(1)
        with open(input_list_path, "r", encoding="utf-8") as f:
            video_paths = [
                Path(line.strip())
                for line in f
                if line.strip() and not line.startswith("#")
            ]
        if not video_paths:
            print(f"No video paths found in {input_list_path}", file=sys.stderr)
            sys.exit(1)

    results = runner.run_batch(
        video_paths,
        config_path=args.config,
        event_callback=event_callback,
        work_dir=work_dir,
        agent_backend=args.agent_backend,
        agent_model=args.agent_model,
        question=args.question,
    )
    _write_jsonl(results, output_path)

    failed = [r for r in results if not r["ok"]]
    if failed:
        print(f"Batch finished with {len(failed)} failure(s):", file=sys.stderr)
        for item in failed:
            print(
                f"  - {item['result']['video_id'] if item['ok'] else item['error']['stage']}: {item['error']['message']}",
                file=sys.stderr,
            )
        sys.exit(1)

    print(f"Results written to {output_path}")


if __name__ == "__main__":
    main()
