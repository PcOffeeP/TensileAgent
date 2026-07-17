"""Shared execution kernel for the iterative agent.

This module is the single entry point used by both the local Web API and
the CLI. It loads configuration, builds the minimal video metadata required by
``IterativeAgent``, wires up the LLM / inference / sampling / clip-building
dependencies, and runs one or more videos.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import yaml

from agent.interaction import parse_user_intent, project_result
from agent.schema import FinalOutput, RunnerError, RunnerResult


def load_config(config_path: str | Path = "agent/config.yaml") -> dict[str, Any]:
    """Load and return the YAML configuration at ``config_path``."""
    path = Path(config_path)
    if path.resolve() == (Path(__file__).parent / "config.yaml").resolve():
        from agent.config_util import load_config as load_effective_config

        return load_effective_config()
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def create_llm_client(config: dict[str, Any]):
    """Create the TensileAgent LLM client from ``config``.

    Delegates to ``agent.llm.AgentLLMFactory``.
    """
    from agent.llm import AgentLLMFactory

    return AgentLLMFactory.create(config)


def create_inference_client(config: dict[str, Any]):
    """Create the fine-tuned model inference client from ``config``.

    Delegates to ``agent.inference.create_inference_client``.
    """
    from agent.inference import create_inference_client as _create_inference_client

    return _create_inference_client(config)


def create_clip_builder(
    config: dict[str, Any], output_dir: str | Path | None = None
):
    """Create a ``FfmpegVideoClipBuilder``.

    Defaults ``output_dir`` to ``data/08_runtime/agent_clips`` if not provided.
    """
    from agent.sampling import FfmpegVideoClipBuilder

    if output_dir is None:
        output_dir = "data/08_runtime/agent_clips"
    return FfmpegVideoClipBuilder(output_dir=str(output_dir))


def build_video_meta(
    video_path: str | Path, video_id: str | None = None
) -> dict[str, Any]:
    """Build the ``video_meta`` dict expected by ``IterativeAgent``.

    ``duration_sec`` is obtained with ``ffprobe`` when available, otherwise via
    ``cv2``. If neither is available, a ``RuntimeError`` is raised.

    Returns:
        A dict with keys ``video_id``, ``video_path``, ``duration_sec``,
        ``duration`` (alias for ``duration_sec``), ``original_fps`` and
        ``total_frames``.
    """
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {path}")

    resolved_id = video_id if video_id is not None else path.stem

    # Prefer ffprobe.
    try:
        from agent.sampling import _probe_video, _which_ffprobe

        _which_ffprobe()
        probe = _probe_video(str(path))
        duration = float(probe["duration"] or 0.0)
        fps = probe["fps"] or 0.0
        total_frames = int(probe["total_frames"] or 0)
        return {
            "video_id": resolved_id,
            "video_path": str(path),
            "duration_sec": duration,
            "duration": duration,
            "original_fps": fps if fps > 0 else None,
            "total_frames": total_frames if total_frames > 0 else None,
        }
    except Exception:
        pass

    # Fall back to cv2.
    try:
        import cv2
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Unable to read video metadata: ffprobe failed and cv2 is not installed."
        ) from exc

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cv2 unable to open video: {path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    if fps <= 0 or total_frames <= 0:
        raise RuntimeError(
            f"Unable to determine video duration from cv2: fps={fps}, frames={total_frames}"
        )

    duration = total_frames / fps
    return {
        "video_id": resolved_id,
        "video_path": str(path),
        "duration_sec": duration,
        "duration": duration,
        "original_fps": float(fps),
        "total_frames": total_frames,
    }


def _runtime_dir(work_dir: str | Path | None, name: str) -> Path:
    """Return a runtime subdirectory path rooted at ``work_dir`` or cwd."""
    if work_dir is None:
        return Path("data/08_runtime") / name
    return Path(work_dir) / "data/08_runtime" / name


def run_one(
    video_path: str | Path,
    config_path: str | Path = "agent/config.yaml",
    video_id: str | None = None,
    event_callback: Callable[[dict], None] | None = None,
    work_dir: str | Path | None = None,
    agent_backend: str | None = None,
    agent_model: str | None = None,
    question: str | None = None,
    trace_task_id: str | None = None,
    agent_config_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the agent on a single video and return a ``RunnerResult`` dict.

    Configuration is loaded from ``config_path`` inside this function. On
    success the dict wraps a ``FinalOutput``; on failure it carries a
    ``RunnerError`` with the stage where the failure occurred.  A
    ``video_failed`` event is emitted (when a callback is provided) before
    the failure envelope is returned.

    Returns a plain ``dict`` (``RunnerResult.model_dump()``) for backward
    compatibility with callers that consume dicts.
    """
    from agent.iterative_agent import IterativeAgent

    path = Path(video_path)
    resolved_id = video_id if video_id is not None else path.stem

    stage = "configuration"
    try:
        intent = parse_user_intent(question)
        if intent.action == "unsupported":
            return {
                "ok": False,
                "result": None,
                "error": {
                    "stage": "input",
                    "code": "unsupported_intent",
                    "message": intent.ambiguity or "未识别到视频分析需求",
                },
                "response": project_result({}, intent),
            }
        config = load_config(config_path)
        config.setdefault("agent", {})
        config["agent"].setdefault("backend", "remote")
        config["agent"].setdefault("remote", {})
        config["agent"].setdefault("local", {})

        # Web tasks pin the complete decision-backend selection at creation
        # time.  This prevents a later config file edit from changing an
        # already queued task.  ``digest`` is provenance metadata and is not
        # forwarded to the OpenAI-compatible client.
        if agent_config_snapshot is not None:
            snapshot_backend = agent_config_snapshot.get("backend")
            if snapshot_backend not in {"local", "remote"}:
                raise ValueError("agent_config_snapshot backend must be local or remote")
            required_fields = ("provider", "model", "base_url", "reasoning_effort")
            missing = [
                field
                for field in required_fields
                if not isinstance(agent_config_snapshot.get(field), str)
                or not agent_config_snapshot[field].strip()
            ]
            if missing:
                raise ValueError(
                    f"agent_config_snapshot missing fields: {', '.join(missing)}"
                )
            reasoning_effort = agent_config_snapshot["reasoning_effort"]
            if reasoning_effort not in {"none", "low", "medium", "high"}:
                raise ValueError("agent_config_snapshot has invalid reasoning_effort")
            if snapshot_backend == "local" and not agent_config_snapshot.get("digest"):
                raise ValueError("local agent_config_snapshot requires digest")
            config["agent"]["backend"] = snapshot_backend
            config["agent"][snapshot_backend] = {
                field: agent_config_snapshot[field] for field in required_fields
            }

        # 允许 CLI 参数覆盖 agent 后端和模型
        if agent_backend is not None:
            config["agent"]["backend"] = agent_backend
        if agent_model is not None:
            backend = agent_backend or config["agent"]["backend"]
            config["agent"][backend]["model"] = agent_model

        config["_runtime"] = {
            "task_id": trace_task_id or resolved_id,
            "llm_trace_root": str(_runtime_dir(work_dir, "llm_traces")),
            "model_digest": (agent_config_snapshot or {}).get("digest"),
        }

        stage = "input"
        video_meta = build_video_meta(path, video_id=resolved_id)

        stage = "decision_backend"
        llm_client = create_llm_client(config)

        stage = "inference_transport"
        inference_client = create_inference_client(config)

        stage = "sampling"
        clip_builder = create_clip_builder(
            config, output_dir=_runtime_dir(work_dir, "agent_clips")
        )

        stage = "internal"
        agent = IterativeAgent(
            config=config,
            video_meta=video_meta,
            llm_client=llm_client,
            clip_builder=clip_builder,
            inference_client=inference_client,
            event_callback=event_callback,
            work_dir=work_dir,
            request_evidence=intent.wants_evidence,
        )
        raw_result = agent.run()
        # ``IterativeAgent.run()`` returns either a dict of public final-output
        # fields (plus metadata) or, on consecutive infrastructure failures, a
        # ``RunnerResult(ok=False, ...)`` envelope.  Propagate failure envelopes
        # directly so the original error code (e.g. ``consecutive_infra_failures``)
        # is not overwritten by a downstream ``ValidationError``.
        if raw_result.get("ok") is False and raw_result.get("error") is not None:
            error = raw_result["error"]
            if event_callback is not None:
                event_callback(
                    {
                        "event_type": "video_failed",
                        "video_id": resolved_id,
                        "error": error.get("message", ""),
                        "stage": error.get("stage", "internal"),
                    }
                )
            return raw_result

        # Normal success path: filter to the public FinalOutput contract fields.
        _FO_FIELDS = {"video_id", "status", "time_range", "fracture_type",
                       "location", "confidence", "visual_evidence", "unrecognized_reason"}
        fo_dict = {k: v for k, v in raw_result.items() if k in _FO_FIELDS}
        # Historical agents returned a model-supplied scalar. It is not a
        # calibrated Agent confidence and must not be re-labelled as one.
        if isinstance(fo_dict.get("confidence"), (int, float)):
            fo_dict["confidence"] = None
        envelope = RunnerResult(
            ok=True, result=FinalOutput(**fo_dict)
        ).model_dump()
        envelope["response"] = project_result(envelope["result"], intent)
        return envelope
    except Exception as exc:
        exc._stage = stage  # type: ignore[attr-defined]
        if event_callback is not None:
            event_callback(
                {
                    "event_type": "video_failed",
                    "video_id": resolved_id,
                    "error": str(exc),
                    "stage": stage,
                }
            )
        return RunnerResult(
            ok=False,
            error=RunnerError(
                stage=stage,
                code=type(exc).__name__,
                message=str(exc),
            ),
        ).model_dump()


def run_batch(
    video_paths: list[str | Path],
    config_path: str | Path = "agent/config.yaml",
    event_callback: Callable[[dict], None] | None = None,
    work_dir: str | Path | None = None,
    agent_backend: str | None = None,
    agent_model: str | None = None,
    question: str | None = None,
) -> list[dict[str, Any]]:
    """Run the agent sequentially on multiple videos.

    Configuration is loaded by each call to ``run_one`` from ``config_path``.
    A single video failure is recorded as a
    ``RunnerResult(ok=False, ...).model_dump()`` dict without interrupting
    the rest of the batch.
    """
    results: list[dict[str, Any]] = []
    for path in video_paths:
        path_obj = Path(path)
        resolved_id = path_obj.stem
        results.append(
            run_one(
                path_obj,
                config_path,
                video_id=resolved_id,
                event_callback=event_callback,
                work_dir=work_dir,
                agent_backend=agent_backend,
                agent_model=agent_model,
                question=question,
            )
        )
    return results
