from __future__ import annotations

import hashlib
import json
from typing import Any
from unittest.mock import MagicMock

from agent.contract import V4_1_EXPECTED_CONTRACT_HASH
from agent.inference import InferenceResult
from agent.iterative_agent import IterativeAgent
from agent.llm import BaseAgentLLM
from agent.sampling import ClipBuildResult


class InitialSampleLLM(BaseAgentLLM):
    """Permit only the initial Planner call; coverage must bypass the LLM."""

    def __init__(self) -> None:
        self.calls = 0

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Any:
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("V4.1 COVERAGE must not call the decision model")

        tool_call = MagicMock()
        tool_call.id = "initial_sample"
        tool_call.type = "function"
        tool_call.function.name = "sample_and_infer"
        tool_call.function.arguments = json.dumps(
            {"sample_range": [0.0, 40.0], "task_mode": "analyze"}
        )
        message = MagicMock()
        message.content = ""
        message.tool_calls = [tool_call]
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        return response

    @property
    def model_name(self) -> str:
        return "static/initial-only"


class RecordingClipBuilder:
    def __init__(self) -> None:
        self.ranges: list[list[float]] = []

    def build_with_manifest(
        self,
        source_video: str,
        sample_range: list[float],
    ) -> ClipBuildResult:
        self.ranges.append(list(sample_range))
        start, end = sample_range
        step = (end - start) / 7
        manifest = [
            {
                "temp_index": index,
                "original_frame": index,
                "timestamp": start + index * step,
            }
            for index in range(8)
        ]
        payload = f"{start}:{end}".encode()
        return ClipBuildResult(
            path=f"clip_{start}_{end}.mp4",
            manifest=manifest,
            file_hash=hashlib.sha256(payload).hexdigest(),
            file_size=len(payload),
        )


class V41InferenceClient:
    contract_version = "tensile-vlm/v4.1"
    deployment_snapshot = {
        "model_version": "test-model",
        "adapter_version": "test-adapter",
        "base_model_version": "test-base",
        "processor_version": "test-processor",
        "llamafactory_version": "test-llamafactory",
        "transformers_version": "test-transformers",
        "config_fingerprint": "test-config",
        "runtime_device": "cpu",
        "runtime_dtype": "float32",
        "contract_version": "tensile-vlm/v4.1",
        "contract_hash": V4_1_EXPECTED_CONTRACT_HASH,
    }

    def __init__(self, outputs: list[dict[str, Any]]) -> None:
        self.outputs = outputs
        self.index = 0

    def infer(self, video_input: ClipBuildResult, prompt: str) -> InferenceResult:
        output = self.outputs[self.index]
        self.index += 1
        return InferenceResult(
            ok=True,
            model_output=output,
            attempts=1,
            preprocessing={
                "request_id": f"request-{self.index}",
                "processor_version": "test",
                "deployment_manifest": self.deployment_snapshot,
                "max_frames": 8,
                "frames": [
                    {"index": index, "timestamp": float(frame["timestamp"])}
                    for index, frame in enumerate(video_input.manifest)
                ],
            },
        )


def _output(
    clip_state: str,
    *,
    special_case: str | None = None,
) -> dict[str, Any]:
    return {
        "clip_state": clip_state,
        "fracture_mechanism": None,
        "fracture_site": None,
        "special_case": special_case,
    }


def _agent(
    outputs: list[dict[str, Any]],
    *,
    max_rounds: int,
    events: list[dict[str, Any]] | None = None,
) -> tuple[IterativeAgent, InitialSampleLLM, RecordingClipBuilder]:
    llm = InitialSampleLLM()
    clip_builder = RecordingClipBuilder()
    agent = IterativeAgent(
        llm_client=llm,
        video_meta={
            "video_id": "v41-coverage",
            "duration": 40.0,
            "video_path": "video.mp4",
        },
        config={
            "agent": {
                "max_rounds": max_rounds,
                "tolerance_seconds": 1.0,
                "temperature": 0.0,
            },
            "backend": {"contract_version": "tensile-vlm/v4.1"},
        },
        clip_builder=clip_builder,
        inference_client=V41InferenceClient(outputs),
        event_callback=(events.append if events is not None else None),
    )
    return agent, llm, clip_builder


def test_v4_1_global_negative_runs_all_coverage_without_planner() -> None:
    events: list[dict[str, Any]] = []
    agent, llm, clip_builder = _agent(
        [_output("未断裂") for _ in range(6)],
        max_rounds=6,
        events=events,
    )

    result = agent.run()

    assert result["status"] == "no_fracture"
    assert llm.calls == 1
    assert clip_builder.ranges == [
        [0.0, 40.0],
        [0.0, 10.0],
        [7.5, 17.5],
        [15.0, 25.0],
        [22.5, 32.5],
        [30.0, 40.0],
    ]
    assert [entry["model"] for entry in result["history"][1:]] == [
        "program/scheduler"
    ] * 5
    scheduler_events = [
        event for event in events if event.get("event_type") == "scheduler_action"
    ]
    assert len(scheduler_events) == 5
    assert all(event["source"] == "coverage_scheduler" for event in scheduler_events)


def test_v4_1_program_rechecks_indeterminate_coverage_on_same_window() -> None:
    agent, llm, clip_builder = _agent(
        [
            _output("未断裂"),
            _output("无法判断", special_case="视频异常"),
            _output("无法判断", special_case="视频异常"),
        ],
        max_rounds=3,
    )

    result = agent.run()

    assert result["status"] == "unrecognized"
    assert result["unrecognized_reason"] == "video_anomaly"
    assert llm.calls == 1
    assert clip_builder.ranges == [
        [0.0, 40.0],
        [0.0, 10.0],
        [0.0, 10.0],
    ]


def test_v4_1_positive_coverage_window_exits_program_owned_scan() -> None:
    agent, llm, clip_builder = _agent(
        [
            _output("未断裂"),
            _output("未断裂"),
            _output("发生断裂"),
        ],
        max_rounds=3,
    )

    result = agent.run()

    assert result["status"] == "unrecognized"
    assert agent.state == "NARROWING"
    assert agent.coverage_index == 1
    assert llm.calls == 1
    assert clip_builder.ranges == [
        [0.0, 40.0],
        [0.0, 10.0],
        [7.5, 17.5],
    ]
