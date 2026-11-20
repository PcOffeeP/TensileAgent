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

    def infer(self, video_input: ClipBuildResult) -> InferenceResult:
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


class ScriptedLLM(BaseAgentLLM):
    """Scripted planner returning a sequence of tool calls for real-guard replays."""

    def __init__(self, calls: list[tuple[str, dict[str, Any]]]) -> None:
        self.script = calls
        self.calls = 0

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> Any:
        del messages, tools, temperature, max_tokens
        idx = min(self.calls, len(self.script) - 1)
        name, arguments = self.script[idx]
        self.calls += 1
        tool_call = MagicMock()
        tool_call.id = f"call-{self.calls}"
        tool_call.type = "function"
        tool_call.function.name = name
        tool_call.function.arguments = json.dumps(arguments, ensure_ascii=False)
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
        return "static/scripted"


def _scripted_agent(
    llm_calls: list[tuple[str, dict[str, Any]]],
    outputs: list[dict[str, Any]],
    *,
    max_rounds: int = 10,
    inference_client: Any | None = None,
) -> tuple[IterativeAgent, ScriptedLLM, RecordingClipBuilder]:
    llm = ScriptedLLM(llm_calls)
    clip_builder = RecordingClipBuilder()
    agent = IterativeAgent(
        llm_client=llm,
        video_meta={
            "video_id": "v41-replay",
            "duration": 40.0,
            "video_path": "video.mp4",
        },
        config={
            "agent": {
                "max_rounds": max_rounds,
                "tolerance_seconds": 1.0,
                "temperature": 0.2,
            },
            "backend": {"contract_version": "tensile-vlm/v4.1"},
        },
        clip_builder=clip_builder,
        inference_client=inference_client or V41InferenceClient(outputs),
    )
    return agent, llm, clip_builder


def test_v4_1_local_negative_after_global_positive_does_not_trigger_coverage() -> None:
    agent, llm, clip_builder = _scripted_agent(
        llm_calls=[
            ("sample_and_infer", {"sample_range": [0.0, 40.0], "task_mode": "analyze"}),
            ("sample_and_infer", {"sample_range": [10.0, 20.0], "task_mode": "analyze"}),
            ("terminate", {"status": "no_fracture"}),
        ],
        outputs=[
            _output("发生断裂"),
            _output("未断裂"),
        ],
        max_rounds=3,
    )

    result = agent.run()

    assert result["status"] == "unrecognized"
    assert result["unrecognized_reason"] == "max_rounds"
    assert agent.state == "NARROWING"
    assert agent.event_bounds.interval == [20.0, 40.0]
    assert agent.candidate == [20.0, 40.0]
    assert clip_builder.ranges == [[0.0, 40.0], [10.0, 20.0]]
    assert llm.calls == 3


def test_v4_1_local_negative_then_local_positive_confirms_fracture() -> None:
    agent, _, clip_builder = _scripted_agent(
        llm_calls=[
            ("sample_and_infer", {"sample_range": [0.0, 40.0], "task_mode": "analyze"}),
            ("sample_and_infer", {"sample_range": [10.0, 20.0], "task_mode": "analyze"}),
            ("sample_and_infer", {"sample_range": [25.0, 25.8], "task_mode": "analyze"}),
            (
                "terminate",
                {
                    "status": "fracture",
                    "evidence_rounds": [0, 2],
                },
            ),
        ],
        outputs=[
            _output("发生断裂"),
            _output("未断裂"),
            _output("发生断裂"),
        ],
        max_rounds=5,
    )

    result = agent.run()

    assert result["status"] == "fracture"
    assert result["time_range"] == [25.0, 25.8]
    assert clip_builder.ranges == [[0.0, 40.0], [10.0, 20.0], [25.0, 25.8]]


def test_v4_1_coverage_rejects_old_window_mixing() -> None:
    agent, _, _ = _scripted_agent(llm_calls=[], outputs=[], max_rounds=10)
    agent.history = [
        {"result": {"ok": True, "sample_range": [0.0, 10.0], "model_output": _output("未断裂")}},
        {"result": {"ok": True, "sample_range": [0.0, 40.0], "model_output": _output("未断裂")}},
        {"result": {"ok": True, "sample_range": [7.5, 17.5], "model_output": _output("未断裂")}},
        {"result": {"ok": True, "sample_range": [15.0, 25.0], "model_output": _output("未断裂")}},
        {"result": {"ok": True, "sample_range": [22.5, 32.5], "model_output": _output("未断裂")}},
        {"result": {"ok": True, "sample_range": [30.0, 40.0], "model_output": _output("未断裂")}},
    ]
    agent.coverage_start_index = 1

    assert agent._has_complete_no_fracture_coverage() is False


def test_v4_1_zero_visual_calls_max_rounds_terminate_rejected() -> None:
    agent, llm, clip_builder = _scripted_agent(
        llm_calls=[
            (
                "terminate",
                {"status": "unrecognized", "unrecognized_reason": "max_rounds"},
            ),
            ("sample_and_infer", {"sample_range": [0.0, 40.0], "task_mode": "analyze"}),
        ],
        outputs=[_output("未断裂") for _ in range(6)],
        max_rounds=10,
    )

    result = agent.run()

    assert result["status"] == "no_fracture"
    assert len(clip_builder.ranges) == 6
    assert llm.calls == 2


def test_v4_1_two_normal_fracture_rounds_cannot_terminate_as_video_anomaly() -> None:
    agent, _, clip_builder = _scripted_agent(
        llm_calls=[
            ("sample_and_infer", {"sample_range": [0.0, 40.0], "task_mode": "analyze"}),
            ("sample_and_infer", {"sample_range": [10.0, 20.0], "task_mode": "analyze"}),
            ("sample_and_infer", {"sample_range": [10.0, 20.0], "task_mode": "analyze"}),
            (
                "terminate",
                {"status": "unrecognized", "unrecognized_reason": "video_anomaly"},
            ),
        ],
        outputs=[
            _output("发生断裂"),
            _output("发生断裂"),
            _output("发生断裂"),
        ],
        max_rounds=4,
    )

    result = agent.run()

    # The bogus video_anomaly termination must be rejected; since rounds 1 and 2
    # are valid local fracture evidence, exhaustion confirms fracture (not video_anomaly).
    assert result["status"] == "fracture"
    assert result["unrecognized_reason"] is None
    assert clip_builder.ranges == [[0.0, 40.0], [10.0, 20.0], [10.0, 20.0]]


def test_v4_1_initial_edge_direction_does_not_loop_on_full_video() -> None:
    for edge_state in ("已断裂", "临界未断裂"):
        agent, _, clip_builder = _scripted_agent(
            llm_calls=[
                (
                    "sample_and_infer",
                    {"sample_range": [0.0, 40.0], "task_mode": "analyze"},
                ),
                (
                    "sample_and_infer",
                    {"sample_range": [0.0, 10.0], "task_mode": "analyze"},
                ),
            ],
            outputs=[
                _output(edge_state),
                _output("发生断裂"),
            ],
            max_rounds=2,
        )

        agent.run()

        assert clip_builder.ranges == [[0.0, 40.0], [0.0, 10.0]]


def test_v4_1_indeterminate_recheck_resolved_negative_advances_coverage() -> None:
    agent, llm, clip_builder = _agent(
        [
            _output("未断裂"),
            _output("无法判断", special_case="视频异常"),
            _output("未断裂"),
            _output("未断裂"),
            _output("未断裂"),
            _output("未断裂"),
            _output("未断裂"),
        ],
        max_rounds=8,
    )

    result = agent.run()

    assert result["status"] == "no_fracture"
    assert llm.calls == 1
    assert clip_builder.ranges == [
        [0.0, 40.0],
        [0.0, 10.0],
        [0.0, 10.0],
        [7.5, 17.5],
        [15.0, 25.0],
        [22.5, 32.5],
        [30.0, 40.0],
    ]


def test_v4_1_missing_preprocessing_and_parse_error_returns_infra_failure() -> None:
    class BadServerClient:
        contract_version = "tensile-vlm/v4.1"
        deployment_snapshot = V41InferenceClient.deployment_snapshot

        def infer(self, video_input: ClipBuildResult) -> InferenceResult:
            del video_input
            return InferenceResult(
                ok=False,
                model_output=None,
                error=MagicMock(
                    code="invalid_json", message="not valid json", field=None
                ),
                attempts=1,
                preprocessing=None,
            )

    agent, _, _ = _scripted_agent(
        llm_calls=[
            ("sample_and_infer", {"sample_range": [0.0, 40.0], "task_mode": "analyze"}),
            ("sample_and_infer", {"sample_range": [0.0, 40.0], "task_mode": "analyze"}),
        ],
        outputs=[],
        max_rounds=4,
        inference_client=BadServerClient(),
    )

    result = agent.run()

    assert result["ok"] is False
    assert result["error"]["code"] == "consecutive_infra_failures"
    assert agent.history[0]["result"]["infra_error"]["code"] == (
        "missing_or_invalid_preprocessing_metadata"
    )
    assert agent.history[0]["result"]["validation_error"]["code"] == "invalid_json"


def test_finalize_contract_violation_returns_internal_error_envelope() -> None:
    agent, _, _ = _scripted_agent(llm_calls=[], outputs=[], max_rounds=2)

    result = agent._finalize(
        {
            "status": "fracture",
            "time_range": [2.0, 3.5],  # violates FinalOutput <= 1.0s invariant
            "fracture_type": None,
            "location": None,
            "confidence": None,
            "unrecognized_reason": None,
        }
    )

    assert result["ok"] is False
    assert result["error"]["stage"] == "internal"
    assert result["error"]["code"] == "final_output_contract_violation"
