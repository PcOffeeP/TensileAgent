from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import json

import pytest

from agent.inference import InferenceResult
from agent.contract import visual_contract_hash
from agent.iterative_agent import IterativeAgent
from agent.llm import BaseAgentLLM
from agent.sampling import ClipBuildResult


TEST_DEPLOYMENT_MANIFEST = {
    "model_version": "minicpm-v-4.5",
    "adapter_version": "adapter-test",
    "processor_version": "minicpmv4.5/0.1",
    "transformers_version": "4.test",
    "llamafactory_version": "test-rev",
    "base_model_version": "base-test",
    "config_fingerprint": "sha256:test",
    "runtime_device": "cpu",
    "runtime_dtype": "float32",
    "contract_version": "tensile-vlm/v2",
    "contract_hash": visual_contract_hash(),
}


@pytest.fixture(autouse=True)
def _isolate_legacy_transition_tests_from_v7_local_evidence_gate(monkeypatch):
    """This module's historical tests target transitions, not evidence scope."""
    monkeypatch.setattr(
        IterativeAgent,
        "_round_is_local_fracture",
        IterativeAgent._round_has_fracture,
    )
    monkeypatch.setattr(
        IterativeAgent,
        "_has_complete_no_fracture_coverage",
        lambda self: self.no_fracture_count >= 1,
    )
    monkeypatch.setattr(
        IterativeAgent,
        "_has_consistent_special_recheck",
        lambda self, reason: True,
    )


class StaticLLM(BaseAgentLLM):
    """LLM that returns a fixed sequence of tool_calls responses."""

    def __init__(self, sequence: list[tuple[str, dict[str, Any]]]) -> None:
        self.sequence = sequence
        self.index = 0

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Any:
        name, args = self.sequence[self.index]
        self.index = min(self.index + 1, len(self.sequence) - 1)

        tool_call = MagicMock()
        tool_call.id = f"call_{self.index}"
        tool_call.type = "function"
        tool_call.function.name = name
        tool_call.function.arguments = __import__("json").dumps(args)

        message = MagicMock()
        message.content = f"calling {name}"
        message.tool_calls = [tool_call]

        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        return response

    @property
    def model_name(self) -> str:
        return "static/test"


class FakeClipBuilder:
    """Clip builder that returns a ``ClipBuildResult`` with a synthetic manifest."""

    def __init__(self):
        pass

    def build_with_manifest(
        self,
        source_video: str,
        sample_range: list[float],
    ) -> ClipBuildResult:
        import hashlib

        start, end = sample_range
        duration = end - start
        n = 8
        step = duration / max(n - 1, 1)
        manifest = [
            {
                "temp_index": k,
                "original_frame": k,
                "timestamp": round(start + k * step, 6),
            }
            for k in range(n)
        ]
        # Deterministic fake file content so hash/size are stable per range.
        fake_bytes = f"clip_{start}_{end}".encode("utf-8")
        return ClipBuildResult(
            path=f"clip_{start}_{end}.mp4",
            manifest=manifest,
            file_hash=hashlib.sha256(fake_bytes).hexdigest(),
            file_size=len(fake_bytes),
        )


class RecordingClipBuilder(FakeClipBuilder):
    def __init__(self):
        self.ranges = []

    def build_with_manifest(self, source_video, sample_range):
        self.ranges.append(list(sample_range))
        return super().build_with_manifest(source_video, sample_range)


class FakeInferenceClient:
    """Returns canned ``InferenceResult`` objects.

    When a dict response carries ``has_fracture=True`` and no explicit
    ``preprocessing`` is provided, a synthetic valid preprocessing is
    injected so that tests exercise the normal server-adapter-installed path.
    """

    def __init__(self, responses: list):
        self.responses = responses
        self.index = 0

    def infer(self, video_input, prompt) -> InferenceResult:
        resp = self.responses[self.index]
        self.index = min(self.index + 1, len(self.responses) - 1)

        if isinstance(resp, InferenceResult):
            return resp

        if isinstance(resp, dict):
            # Older state-machine tests were authored against the retired
            # 36-frame protocol.  Normalize only those in-range legacy fixture
            # indices to the current 8-frame model contract.  Deliberately
            # invalid values such as [100, 101] remain invalid.
            resp = deepcopy(resp)
            fracture_between = resp.get("fracture_between")
            if (
                resp.get("has_fracture") is True
                and isinstance(fracture_between, list)
                and len(fracture_between) == 2
                and 7 < fracture_between[1] < 36
            ):
                center = sum(fracture_between) / 2
                left = min(6, max(0, int(center * 8 / 36)))
                resp["fracture_between"] = [left, left + 1]

            # Auto-inject valid preprocessing for every semantic response
            # when the caller didn't explicitly set _preprocessing.
            # Explicit _preprocessing=None means "test missing-preprocessing path".
            pp = resp.get("_preprocessing")
            if "_preprocessing" not in resp:
                manifest = getattr(video_input, "manifest", None) or []
                if len(manifest) <= 8:
                    selected = manifest
                else:
                    selected_indices = [
                        round(i * (len(manifest) - 1) / 7) for i in range(8)
                    ]
                    selected = [manifest[i] for i in selected_indices]
                pp = {
                    "request_id": "fake-uuid",
                    "processor_version": "minicpmv4.5/0.1",
                    "deployment_manifest": TEST_DEPLOYMENT_MANIFEST,
                    "max_frames": 8,
                    "frames": [
                        {
                            # ``index`` is the model-input position; the
                            # timestamp carries the mapping to the clip.
                            "index": i,
                            "timestamp": float(frame.get("clip_timestamp", frame["timestamp"])),
                        }
                        for i, frame in enumerate(selected)
                    ],
                }
            return InferenceResult(
                ok=True,
                model_output=resp,
                attempts=1,
                preprocessing=pp,
            )

        if resp is None:
            return InferenceResult(
                ok=False,
                model_output=None,
                error=MagicMock(code="inference_failed", message="模型输出解析失败", field=None),
                attempts=1,
            )

        # String: parse via ResultParser to produce ok/error.
        from agent.parser import ResultParser
        parsed = ResultParser.parse(resp)
        if parsed.ok:
            return InferenceResult(ok=True, model_output=parsed.data, attempts=1)
        return InferenceResult(ok=False, error=parsed.error, attempts=1)


def make_config():
    return {
        "agent": {
            "tolerance_seconds": 1.0,
            "max_rounds": 5,
            "confidence_threshold": 0.5,
            "max_low_conf_rounds": 2,
            "temperature": 0.0,
        }
    }


def test_iterative_agent_terminates_on_converged_fracture():
    video_meta = {"video_id": "v001", "duration": 100.0, "video_path": "v001.mp4"}
    config = make_config()

    # Model returns fracture between frames 17-18 of 36.
    # With video_fps=8, duration=100, effective frames = min(36, 800) = 36.
    # Timestamps: k * 100 / 35. fracture_between [17,18] -> [48.571429, 51.428571].
    responses = [
        {
            "has_fracture": True,
            "fracture_between": [17, 18],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
        },
        {
            "has_fracture": True,
            "fracture_between": [17, 18],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
        },
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0],
        }),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["rounds"] == 2
    assert result["fracture_type"] == "韧性断裂"
    assert result["location"] == "inside_gauge"
    assert result["rounds"] == 2
    assert result["confidence"] is not None


def test_iterative_agent_no_fracture_global_scope():
    video_meta = {"video_id": "v002", "duration": 60.0, "video_path": "v002.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    responses = [
        {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.95},
        {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.95},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "no_fracture",
            "confidence": 0.95,
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "no_fracture"
    assert result["fracture_type"] is None
    assert result["location"] is None
    assert result["time_range"] is None
    assert result["rounds"] == 2


def test_iterative_agent_rejects_early_terminate_until_converged():
    """Early fracture termination without convergence must be rejected."""
    video_meta = {"video_id": "v003", "duration": 100.0, "video_path": "v003.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 4

    responses = [
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        # Round 0: sample full range.
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        # Round 1: LLM tries to terminate with only 1 evidence round -> rejected.
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0],
        }),
        # Round 2: sample narrowed range.
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        # Round 3: terminate with 2 evidence rounds -> allowed.
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"


def test_initial_round_forces_complete_video_against_decision_model_subrange():
    video_meta = {"video_id": "v_initial", "duration": 100.0, "video_path": "v.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 1
    clip_builder = RecordingClipBuilder()
    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [40.0, 45.0], "prompt": "analyze"}),
    ])
    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=clip_builder,
        inference_client=FakeInferenceClient([
            {
                "has_fracture": False,
                "fracture_between": None,
                "type": "未断裂",
                "location": None,
                "confidence": 0.9,
            }
        ]),
    )

    agent.run()

    assert clip_builder.ranges == [[0.0, 100.0]]


def test_iterative_agent_handles_parse_error():
    video_meta = {"video_id": "v005", "duration": 100.0, "video_path": "v005.mp4"}
    config = make_config()
    config["agent"]["tolerance_seconds"] = 5.0
    config["agent"]["max_rounds"] = 3

    # First response is a parse failure as a string.
    responses = [
        "this is not valid json",
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "unrecognized"
    # The first round must carry a validation_error description.
    assert result["history"][0]["result"]["validation_error"]
    assert "invalid" in str(result["history"][0]["result"]["validation_error"]).lower()


def test_iterative_agent_rejects_boundary_sentinel_as_parse_error():
    """A boundary sentinel [0,0] / [N-1,N-1] is rejected as a strict-adjacency parse error."""
    video_meta = {"video_id": "v004", "duration": 100.0, "video_path": "v004.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 4
    config["agent"]["tolerance_seconds"] = 5.0

    responses = [
        # Round 0: full range, valid fracture in the middle.
        {"has_fracture": True, "fracture_between": [17, 18], "type": "脆性断裂", "location": "inside_gauge", "confidence": 0.85},
        # Round 1: focused interval returns illegal boundary sentinel.
        # The parser rejects [0,0] because it's not strictly adjacent [i, i+1].
        {"has_fracture": True, "fracture_between": [0, 0], "type": "脆性断裂", "location": "inside_gauge", "confidence": 0.85},
        # Round 2: focused interval returns valid left-edge adjacent pair.
        {"has_fracture": True, "fracture_between": [0, 1], "type": "脆性断裂", "location": "inside_gauge", "confidence": 0.90},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "脆性断裂",
            "location": "inside_gauge",
            "confidence": 0.90,
            "evidence_rounds": [0, 2],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["fracture_type"] == "脆性断裂"
    # Round 1 must carry a validation_error for the non-adjacent sentinel.
    assert result["history"][1]["result"]["validation_error"]
    assert "严格相邻" in result["history"][1]["result"]["validation_error"]["message"]
    assert result["rounds"] == 3


def test_iterative_agent_focus_false_expands_candidate():
    """A focused sub-interval returning has_fracture=false is a focus miss, not a conflict."""
    video_meta = {"video_id": "v006", "duration": 100.0, "video_path": "v006.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 4

    responses = [
        # Round 0: full range, fracture in the middle.
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        # Round 1: focused interval returns false -> focus miss, expand candidate.
        {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.80},
        # Round 2: expanded interval returns a converged normal interval.
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [47.857143, 52.142857], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 2],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["fracture_type"] == "韧性断裂"
    # Focus misses must not pollute the conflict counter.
    assert agent.conflict_count == 0
    assert result["history"][1]["result"].get("fallback") == "focus_false_expanded_to_parent_range"


def test_iterative_agent_conflict_expands_candidate():
    """A high-confidence result outside the candidate triggers conflict expansion."""
    video_meta = {"video_id": "v007", "duration": 100.0, "video_path": "v007.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 4

    responses = [
        # Round 0: full range, fracture in the middle.
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        # Round 1: wider interval returns a range entirely left of the candidate.
        {"has_fracture": True, "fracture_between": [0, 1], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.88},
        # Round 2: re-sample the expanded candidate and converge.
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 20.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [44.0, 47.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 2],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["fracture_type"] == "韧性断裂"
    assert result["history"][1]["result"].get("conflict_handled") == "expanded_candidate"


def test_iterative_agent_does_not_trust_legacy_model_confidence():
    """Legacy confidence numbers never decide whether conflicting evidence is kept."""
    video_meta = {"video_id": "v008", "duration": 100.0, "video_path": "v008.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 5
    config["agent"]["confidence_threshold"] = 0.5

    responses = [
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        {"has_fracture": True, "fracture_between": [0, 1], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.3},
        {"has_fracture": True, "fracture_between": [0, 1], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.3},
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 20.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 20.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [47.857143, 52.142857], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 3],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["has_fracture"] is True
    assert all(
        entry["result"].get("conflict_handled") != "discarded_low_confidence"
        for entry in result["history"]
    )


def test_iterative_agent_out_of_bounds_fracture_between():
    """An out-of-range fracture_between must become a validation_error, not an IndexError."""
    video_meta = {"video_id": "v009", "duration": 100.0, "video_path": "v009.mp4"}
    config = make_config()
    config["agent"]["tolerance_seconds"] = 5.0
    config["agent"]["max_rounds"] = 5

    # Use explicit preprocessing with 8 frames to ensure [100,101] is out-of-range.
    responses = [
        {
            "has_fracture": True,
            "fracture_between": [100, 101],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "_preprocessing": {
                "request_id": "uuid-oob",
                "processor_version": "minicpmv4.5/0.1",
                "deployment_manifest": TEST_DEPLOYMENT_MANIFEST,
                "max_frames": 8,
                "frames": [{"index": i, "timestamp": float(i)} for i in range(8)],
            },
        },
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [1, 2],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["fracture_type"] == "韧性断裂"
    # The first round must carry an out-of-range validation_error and no interval.
    assert result["history"][0]["result"]["validation_error"]
    assert "超出" in result["history"][0]["result"]["validation_error"]["message"]
    assert "索引范围" in result["history"][0]["result"]["validation_error"]["message"]
    assert result["history"][0]["result"]["inferred_time_range"] is None
    assert result["history"][0]["result"]["inferred_frame_range"] is None


def test_iterative_agent_inference_returns_none_is_parse_error():
    """If InferenceClient.infer returns ok=False, the agent records a validation error."""
    video_meta = {"video_id": "v010", "duration": 100.0, "video_path": "v010.mp4"}
    config = make_config()
    config["agent"]["tolerance_seconds"] = 5.0
    config["agent"]["max_rounds"] = 3

    responses = [
        None,  # signals inference failure
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "unrecognized"
    assert result["history"][0]["result"]["validation_error"]
    assert result["history"][0]["result"]["model_output"] is None


class RecordingLLM(BaseAgentLLM):
    """LLM that records the messages seen on every call."""

    def __init__(self, sequence: list[tuple[str, dict[str, Any]]]) -> None:
        self.sequence = sequence
        self.index = 0
        self.calls: list[list[dict[str, Any]]] = []

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Any:
        self.calls.append(deepcopy(messages))
        name, args = self.sequence[self.index]
        self.index = min(self.index + 1, len(self.sequence) - 1)

        tool_call = MagicMock()
        tool_call.id = f"call_{self.index}"
        tool_call.type = "function"
        tool_call.function.name = name
        tool_call.function.arguments = json.dumps(args)

        message = MagicMock()
        message.content = f"calling {name}"
        message.tool_calls = [tool_call]

        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        return response

    @property
    def model_name(self) -> str:
        return "static/test"


def test_terminate_uses_code_layer_aggregation_not_llm_args():
    """LLM terminate args disagreeing with history must be overridden by code-layer aggregation."""
    video_meta = {"video_id": "v101", "duration": 100.0, "video_path": "v101.mp4"}
    config = make_config()

    # Both positive rounds predict 脆性断裂; round 1 is narrower and becomes best.
    responses = [
        {"has_fracture": True, "fracture_between": [17, 18], "type": "脆性断裂", "location": "inside_gauge", "confidence": 0.92},
        {"has_fracture": True, "fracture_between": [15, 16], "type": "脆性断裂", "location": "inside_gauge", "confidence": 0.91},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",  # LLM proposes wrong type
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    # Code-layer aggregation should pick the majority vote (脆性断裂), not LLM's 韧性断裂.
    assert result["fracture_type"] == "脆性断裂"
    # The time_range must come from the best (narrower) round.
    best_round = result["history"][1]["result"]
    assert result["time_range"] == best_round["inferred_time_range"]


def test_no_fracture_terminate_uses_contract_schema():
    """No-fracture termination produces FinalOutput-compatible fields."""
    video_meta = {"video_id": "v102", "duration": 60.0, "video_path": "v102.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    responses = [
        {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.95},
        {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.95},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "no_fracture",
            "confidence": 0.95,
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "no_fracture"
    assert result["fracture_type"] is None
    assert result["location"] is None
    assert result["time_range"] is None
    assert result["unrecognized_reason"] is None


def test_each_round_appends_updated_state_context():
    """After every sample_and_infer round a fresh user context must be appended."""
    video_meta = {"video_id": "v103", "duration": 100.0, "video_path": "v103.mp4"}
    config = make_config()

    responses = [
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        {"has_fracture": True, "fracture_between": [15, 16], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = RecordingLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    agent.run()
    # Three LLM calls: initial, after round 0, after round 1.
    assert len(llm.calls) == 3

    # Initial call only has system + first user context.
    assert len(llm.calls[0]) == 2

    # Second call must include the updated state context after round 0.
    assert len(llm.calls[1]) == 5
    assert llm.calls[1][-1]["role"] == "user"
    assert "当前候选区间" in llm.calls[1][-1]["content"]

    # Third call must include the state context after round 1 (narrower candidate).
    assert len(llm.calls[2]) == 8
    assert llm.calls[2][-1]["role"] == "user"
    assert "当前候选区间" in llm.calls[2][-1]["content"]


def test_positive_without_inferred_range_is_partial():
    video_meta = {"video_id": "v201", "duration": 100.0, "video_path": "v201.mp4"}
    config = make_config()
    llm = StaticLLM([])
    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient([]),
    )

    positive_rounds = [
        {
            "result": {
                "sample_range": [40.0, 45.0],
                "inferred_time_range": [42.0, 43.0],
                "model_output": {
                    "has_fracture": True,
                    "type": "韧性断裂",
                    "location": "inside_gauge",
                    "confidence": 0.92,
                },
                "manifest": [
                    {"timestamp": 10.0, "original_frame": 80},
                    {"timestamp": 20.0, "original_frame": 160},
                ],
                "inferred_time_range": None,
                "inferred_frame_range": None,
            }
        }
    ]

    # No inferred ranges must remain unavailable, never use the candidate as evidence.
    tool_args = {
        "status": "fracture",
        "fracture_type": "韧性断裂",
        "location": "inside_gauge",
        "confidence": 0.92,
    }
    args = agent._build_fracture_args(positive_rounds, tool_args)
    assert args["status"] == "fracture"
    assert args["time_range"] is None
    assert args["fracture_type"] is None


def test_build_fracture_args_all_invalid_types_stays_positive_partial():
    video_meta = {"video_id": "v202", "duration": 100.0, "video_path": "v202.mp4"}
    config = make_config()
    llm = StaticLLM([])
    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient([]),
    )

    positive_rounds = [
        {
            "result": {
                "model_output": {
                    "has_fracture": True,
                    "type": "invalid_type",
                    "location": "inside_gauge",
                    "confidence": 0.92,
                },
                "manifest": [
                    {"timestamp": 10.0, "original_frame": 80},
                    {"timestamp": 20.0, "original_frame": 160},
                ],
                "inferred_time_range": [10.0, 20.0],
                "inferred_frame_range": [80, 160],
            }
        }
    ]
    tool_args = {
        "status": "fracture",
        "fracture_type": "another_invalid_type",
        "location": "inside_gauge",
        "confidence": 0.92,
    }

    args = agent._build_fracture_args(positive_rounds, tool_args)
    assert args["status"] == "fracture"
    assert args["fracture_type"] is None
    assert args["location"] is None
    # Detection remains positive while type/location are independently unavailable.
    final = agent._finalize(args)
    assert final["status"] == "fracture"
    assert final["time_range"] is None
    assert final["field_status"]["fracture_type"] == "unavailable"


def test_force_terminate_no_fracture_state_ignores_positive_history(caplog):
    """NO_FRACTURE state forces a no-fracture output even if history contains positive rounds."""
    video_meta = {"video_id": "v203", "duration": 100.0, "video_path": "v203.mp4"}
    config = make_config()
    llm = StaticLLM([])
    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient([]),
    )
    agent.state = "NO_FRACTURE"
    agent.history = [
        {
            "result": {
                "sample_range": [40.0, 45.0],
                "inferred_time_range": [42.0, 43.0],
                "model_output": {
                    "has_fracture": True,
                    "type": "韧性断裂",
                    "location": "inside_gauge",
                    "confidence": 0.92,
                }
            }
        }
    ]

    with caplog.at_level("INFO", logger="agent.iterative_agent"):
        result = agent._force_terminate()

    assert result["status"] == "no_fracture"
    assert result["fracture_type"] is None
    assert result["location"] is None


def test_unrecognized_termination():
    """Model explicitly reports unrecognized -> agent accepts the termination."""
    video_meta = {"video_id": "v300", "duration": 100.0, "video_path": "v300.mp4"}
    config = make_config()

    responses = [
        {"has_fracture": None, "fracture_between": None, "type": "视频异常", "location": None, "confidence": 0.7},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "unrecognized",
            "unrecognized_reason": "video_anomaly",
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "unrecognized"
    assert result["unrecognized_reason"] == "video_anomaly"
    assert result["time_range"] is None
    assert result["fracture_type"] is None
    assert result["location"] is None
    assert result["confidence"] is None


def test_unrecognized_termination_invalid_reason_rejected():
    """Invalid unrecognized_reason is rejected by _can_terminate."""
    video_meta = {"video_id": "v301", "duration": 100.0, "video_path": "v301.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    responses = [
        {"has_fracture": None, "fracture_between": None, "type": "视频异常", "location": None, "confidence": 0.7},
        {"has_fracture": None, "fracture_between": None, "type": "视频异常", "location": None, "confidence": 0.7},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "unrecognized",
            "unrecognized_reason": "bad_reason",
        }),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    # With invalid unrecognized_reason, the terminate is rejected.
    # After max_rounds, force_terminate kicks in with no positive rounds -> no_fracture.
    assert result["status"] in ("no_fracture", "unrecognized")


# ---------------------------------------------------------------------------
# Preprocessing metadata integration
# ---------------------------------------------------------------------------
def test_iterative_agent_uses_server_frames_when_preprocessing_valid():
    """With valid server preprocessing, fracture_between maps via server frames."""
    video_meta = {"video_id": "v400", "duration": 100.0, "video_path": "v400.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 4

    # Server frames with timestamps that match FakeClipBuilder's local manifest.
    server_frames = [
        {"index": 0, "timestamp": 0.0},
        {"index": 1, "timestamp": 14.285714},
    ]
    preprocessing = {
        "request_id": "uuid-400",
        "processor_version": "minicpmv4.5/0.1",
        "deployment_manifest": TEST_DEPLOYMENT_MANIFEST,
        "max_frames": 8,
        "frames": server_frames,
    }

    # All rounds use fracture_between [0,1] to ensure overlapping time ranges.
    responses = [
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": True,
                "fracture_between": [0, 1],
                "type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.92,
            },
            attempts=1,
            preprocessing=preprocessing,
        ),
        {"has_fracture": True, "fracture_between": [0, 1], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.91},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 2.857143], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    # Round 0 uses the server-selected actual frame timestamps.
    round0 = result["history"][0]["result"]
    assert round0["inferred_time_range"] == [0.0, 14.285714]


def test_iterative_agent_missing_preprocessing_with_fracture_fails():
    """Missing preprocessing + has_fracture=True must fail per contract (Fix 2)."""
    video_meta = {"video_id": "v401", "duration": 100.0, "video_path": "v401.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    # No preprocessing — InferenceResult.preprocessing defaults to None.
    responses = [
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": True,
                "fracture_between": [3, 4],
                "type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.92,
            },
            attempts=1,
            # preprocessing=None by default
        ),
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": False,
                "fracture_between": None,
                "type": "未断裂",
                "location": None,
                "confidence": 0.95,
            },
            attempts=1,
            # preprocessing=None by default — OK because has_fracture=False
        ),
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "no_fracture",
            "confidence": 0.95,
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["ok"] is False
    assert result["error"]["stage"] == "inference_transport"
    assert result["error"]["code"] == "consecutive_infra_failures"


def test_iterative_agent_missing_preprocessing_no_fracture_graceful():
    """Missing preprocessing + has_fracture=False graceful degrade (Fix 2 compatible path)."""
    video_meta = {"video_id": "v401b", "duration": 60.0, "video_path": "v401b.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    responses = [
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": False,
                "fracture_between": None,
                "type": "未断裂",
                "location": None,
                "confidence": 0.95,
            },
            attempts=1,
        ),
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": False,
                "fracture_between": None,
                "type": "未断裂",
                "location": None,
                "confidence": 0.95,
            },
            attempts=1,
        ),
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "no_fracture",
            "confidence": 0.95,
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["ok"] is False
    assert result["error"]["code"] == "consecutive_infra_failures"


def test_fake_inference_client_explicit_no_preprocessing_with_fracture():
    """FakeInferenceClient dict with _preprocessing=None + has_fracture=True must fail (Fix 2)."""
    video_meta = {"video_id": "v401c", "duration": 100.0, "video_path": "v401c.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    # Explicit _preprocessing=None bypasses auto-injection; triggers the missing-preprocessing error.
    responses = [
        {
            "has_fracture": True,
            "fracture_between": [17, 18],
            "type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "_preprocessing": None,
        },
        {
            "has_fracture": False,
            "fracture_between": None,
            "type": "未断裂",
            "location": None,
            "confidence": 0.95,
        },
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "no_fracture",
            "confidence": 0.95,
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "unrecognized"
    assert result["has_fracture"] is None


def test_iterative_agent_invalid_preprocessing_too_many_frames_errors():
    """Preprocessing with too many frames (> max_frames) causes round failure."""
    video_meta = {"video_id": "v402", "duration": 100.0, "video_path": "v402.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 5

    preprocessing = {
        "request_id": "uuid-402",
        "processor_version": "wrong-version",
        "deployment_manifest": TEST_DEPLOYMENT_MANIFEST,
        "max_frames": 4,
        "frames": [{"index": 0, "timestamp": 0.0}, {"index": 1, "timestamp": 1.0},
                   {"index": 2, "timestamp": 2.0}, {"index": 3, "timestamp": 3.0},
                   {"index": 4, "timestamp": 4.0}],  # 5 frames > max_frames=4
    }

    responses = [
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": True,
                "fracture_between": [0, 1],
                "type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.92,
            },
            attempts=1,
            preprocessing=preprocessing,  # Present but invalid
        ),
        # Subsequent rounds use the normal valid 8-frame server fixture.
        {"has_fracture": True, "fracture_between": [3, 4], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        {"has_fracture": True, "fracture_between": [3, 4], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [1],
        }),
        ("sample_and_infer", {"sample_range": [48.0, 52.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [1, 2],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["has_fracture"] is True


def test_iterative_agent_too_many_frames_preprocessing_error():
    """Preprocessing with >8 frames causes round failure."""
    video_meta = {"video_id": "v403", "duration": 100.0, "video_path": "v403.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    preprocessing = {
        "request_id": "uuid-403",
        "processor_version": "minicpmv4.5/0.1",
        "deployment_manifest": TEST_DEPLOYMENT_MANIFEST,
        "max_frames": 8,
        "frames": [{"index": i, "timestamp": float(i)} for i in range(9)],  # 9 frames > 8
    }

    responses = [
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": True,
                "fracture_between": [0, 1],
                "type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.92,
            },
            attempts=1,
            preprocessing=preprocessing,
        ),
        InferenceResult(
            ok=True,
            model_output={
                "has_fracture": False,
                "fracture_between": None,
                "type": "未断裂",
                "location": None,
                "confidence": 0.95,
            },
            attempts=1,
        ),
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "no_fracture",
            "confidence": 0.95,
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["ok"] is False
    assert result["error"]["code"] == "consecutive_infra_failures"


# =============================================================================
# Fix 7: Pydantic schema validation for tool call arguments
# =============================================================================

def test_pydantic_validation_catches_invalid_sample_and_infer_args():
    """LLM returns invalid sample_range → ValidationError caught, agent continues."""
    video_meta = {"video_id": "v501", "duration": 100.0, "video_path": "v501.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 4

    responses = [
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        # Round 0: bad sample_range (3 elements instead of 2) → Pydantic rejects
        ("sample_and_infer", {"sample_range": [0.0, 50.0, 100.0], "prompt": "analyze"}),
        # Round 1: valid sample
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        # Round 2: valid sample (narrowed)
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    # Agent should recover from the bad tool call and reach a conclusion.
    assert result["status"] == "fracture"
    # The bad tool call should not create a history entry (validation failed before execution).
    assert result["rounds"] >= 2


def test_pydantic_validation_catches_invalid_terminate_args():
    """LLM returns invalid terminate fields → ValidationError caught, agent continues."""
    video_meta = {"video_id": "v502", "duration": 100.0, "video_path": "v502.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 5

    responses = [
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        # Bad terminate: fracture_type is invalid for "fracture" status
        ("terminate", {
            "status": "fracture",
            "fracture_type": "未断裂",  # invalid for fracture status
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0],
        }),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"
    assert result["fracture_type"] == "韧性断裂"


def test_pydantic_validation_catches_missing_required_fields():
    """LLM omits required fields → Pydantic ValidationError, agent continues."""
    video_meta = {"video_id": "v503", "duration": 100.0, "video_path": "v503.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 5

    responses = [
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        # Bad terminate: missing confidence for fracture status
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            # confidence is missing
            "evidence_rounds": [0],
        }),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"


def test_pydantic_validation_catches_state_field_mutual_exclusion():
    """Terminate with fracture status but unrecognized_reason set → model_validator rejects."""
    video_meta = {"video_id": "v504", "duration": 100.0, "video_path": "v504.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 5

    responses = [
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        # Bad: fracture status with unrecognized_reason set (mutually exclusive)
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "unrecognized_reason": "max_rounds",  # must be null for fracture
            "evidence_rounds": [0],
        }),
        ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "fracture"


# =============================================================================
# Fix 3a: intersection check in _can_terminate
# =============================================================================

def test_can_terminate_rejects_non_overlapping_evidence_ranges():
    """Positive evidence rounds with disjoint time ranges must be rejected."""
    video_meta = {"video_id": "v601", "duration": 100.0, "video_path": "v601.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 5

    # Two fracture rounds with non-overlapping ranges.
    responses = [
        {"has_fracture": True, "fracture_between": [1, 2], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        {"has_fracture": True, "fracture_between": [30, 31], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 20.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [80.0, 100.0], "prompt": "analyze"}),
        # Terminate with both evidence rounds — should be rejected due to non-overlapping ranges.
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
        # Agent continues sampling.
        ("sample_and_infer", {"sample_range": [96.0, 100.0], "prompt": "analyze"}),
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [1, 2],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    # Should still reach a conclusion after additional rounds.
    assert result["status"] == "fracture"


# =============================================================================
# Fix 3b: intersection in _build_fracture_args
# =============================================================================

def test_build_fracture_args_uses_intersection_of_all_positive_ranges():
    """_build_fracture_args must use intersection of all positive rounds' time ranges."""
    video_meta = {"video_id": "v701", "duration": 100.0, "video_path": "v701.mp4"}
    config = make_config()
    llm = StaticLLM([])
    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient([]),
    )

    # Three positive rounds with overlapping but different time ranges.
    positive_rounds = [
        {
            "result": {
                "model_output": {
                    "has_fracture": True,
                    "type": "韧性断裂",
                    "location": "inside_gauge",
                    "confidence": 0.92,
                },
                "manifest": [
                    {"timestamp": 10.0, "original_frame": 80},
                    {"timestamp": 20.0, "original_frame": 160},
                ],
                "inferred_time_range": [15.0, 25.0],
                "inferred_frame_range": [120, 200],
                "round_confidence_level": "高",
            }
        },
        {
            "result": {
                "model_output": {
                    "has_fracture": True,
                    "type": "韧性断裂",
                    "location": "inside_gauge",
                    "confidence": 0.91,
                },
                "manifest": [
                    {"timestamp": 10.0, "original_frame": 80},
                    {"timestamp": 20.0, "original_frame": 160},
                ],
                "inferred_time_range": [17.0, 22.0],  # narrower, subset of above
                "inferred_frame_range": [136, 176],
                "round_confidence_level": "高",
            }
        },
        {
            "result": {
                "model_output": {
                    "has_fracture": True,
                    "type": "韧性断裂",
                    "location": "inside_gauge",
                    "confidence": 0.88,
                },
                "manifest": [
                    {"timestamp": 10.0, "original_frame": 80},
                    {"timestamp": 20.0, "original_frame": 160},
                ],
                "inferred_time_range": [18.0, 24.0],
                "inferred_frame_range": [144, 192],
                "round_confidence_level": "中",
            }
        },
    ]

    tool_args = {
        "status": "fracture",
        "fracture_type": "韧性断裂",
        "location": "inside_gauge",
        "confidence": 0.92,
    }

    args = agent._build_fracture_args(positive_rounds, tool_args)
    assert args["status"] == "fracture"
    # Intersection [18,22] exceeds the 1-second tolerance, so localization is unavailable.
    assert args["time_range"] is None
    assert args["fracture_type"] == "韧性断裂"


# =============================================================================
# Fix 3c: max_rounds convergence check
# =============================================================================

def test_max_rounds_rejects_non_converged_candidate():
    """At max_rounds, candidate must be within k*tolerance to terminate."""
    video_meta = {"video_id": "v801", "duration": 100.0, "video_path": "v801.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3
    config["agent"]["tolerance_seconds"] = 1.0

    # Two fracture rounds, but candidate stays wide (> 2*tolerance).
    responses = [
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
        # Round 2: at max_rounds-1, terminate is rejected because candidate width > 2*tolerance.
        ("terminate", {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
            "evidence_rounds": [0, 1],
        }),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    # Detection can still close while localization remains a partial field.
    assert result["status"] == "fracture"
    assert result["has_fracture"] is True


def test_runtime_max_prompt_length_config_override():
    """Runtime config max_prompt_length can be stricter than the schema max_length."""
    video_meta = {"video_id": "v900", "duration": 100.0, "video_path": "v900.mp4"}
    config = make_config()
    config["agent"]["max_prompt_length"] = 10

    llm = StaticLLM([])
    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient([]),
    )

    result = agent._execute_sample_and_infer({
        "sample_range": [0.0, 100.0],
        "prompt": "this prompt is way too long",
    }, round_idx=0)
    assert result["ok"] is False
    assert result["validation_error"]["code"] == "prompt_too_long"
    assert result["validation_error"]["field"] == "prompt"
    assert "max_prompt_length" in result["validation_error"]["message"]


# ---------------------------------------------------------------------------
# Diagnostics persistence and content
# ---------------------------------------------------------------------------
def test_diagnostics_persisted_to_runtime_dir(tmp_path: Path):
    """IterativeAgent must write per-round diagnostics and a summary JSON."""
    video_meta = {"video_id": "v800", "duration": 60.0, "video_path": "v800.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    responses = [
        {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.95},
        {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.95},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("terminate", {"status": "no_fracture", "confidence": 0.95}),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
        work_dir=str(tmp_path),
    )

    result = agent.run()
    assert result["status"] == "no_fracture"

    diag_dir = tmp_path / "data" / "08_runtime" / "diagnostics"
    assert diag_dir.exists()
    round_files = sorted(diag_dir.glob("v800_round_*_diagnostics.json"))
    assert len(round_files) == 2
    for f in round_files:
        data = json.loads(f.read_text(encoding="utf-8"))
        assert "elapsed_seconds" in data

    summary_file = diag_dir / "v800_diagnostics_summary.json"
    assert summary_file.exists()
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    assert summary["video_id"] == "v800"
    assert summary["status"] == "no_fracture"
    assert "history" in summary


def test_summary_redacts_model_video_path(tmp_path: Path):
    """``_persist_summary`` must redact ``history[].result.model_video_path``."""
    video_meta = {"video_id": "v800r", "duration": 60.0, "video_path": "v800r.mp4"}
    agent = IterativeAgent(
        llm_client=StaticLLM([]),
        video_meta=video_meta,
        config=make_config(),
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient([]),
        work_dir=str(tmp_path),
    )

    sensitive_path = "/tmp/agent_clips/secret_clip.mp4"
    result = {
        "video_id": "v800r",
        "status": "no_fracture",
        "confidence": 0.95,
        "rounds": 2,
        "history": [
            {
                "round": 0,
                "result": {
                    "ok": True,
                    "model_video_path": sensitive_path,
                    "model_output": {"has_fracture": False},
                },
            },
            {
                "round": 1,
                "result": {
                    "ok": False,
                    "model_video_path": None,
                    "infra_error": {"code": "sampling_error"},
                },
            },
        ],
    }

    agent._persist_summary(result)

    summary_file = tmp_path / "data" / "08_runtime" / "diagnostics" / "v800r_diagnostics_summary.json"
    assert summary_file.exists()
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    assert summary["history"][0]["result"]["model_video_path"] == "[REDACTED]"
    assert summary["history"][1]["result"]["model_video_path"] is None
    assert sensitive_path not in summary_file.read_text(encoding="utf-8")
    # The in-memory result must keep the original path.
    assert result["history"][0]["result"]["model_video_path"] == sensitive_path


def test_visual_indeterminate_diagnostics():
    video_meta = {"video_id": "v810", "duration": 60.0, "video_path": "v810.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 2

    responses = [
        {"has_fracture": None, "fracture_between": None, "type": None, "location": None, "confidence": 0.7},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("terminate", {"status": "unrecognized", "unrecognized_reason": "visual_indeterminate"}),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "unrecognized"
    diag = result["history"][0]["result"]["diagnostics"]
    assert diag["video_anomaly_kind"] == "visual_indeterminate"


def test_positive_without_secondary_fields_is_not_visual_unknown():
    video_meta = {"video_id": "v811", "duration": 60.0, "video_path": "v811.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 2

    responses = [
        {"has_fracture": True, "fracture_between": None, "type": None, "location": None, "confidence": 0.7},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("terminate", {"status": "unrecognized", "unrecognized_reason": "visual_indeterminate"}),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    assert result["status"] == "unrecognized"
    diag = result["history"][0]["result"]["diagnostics"]
    assert "video_anomaly_kind" not in diag
    assert agent.candidate == [0.0, 60.0]
    assert agent._round_has_fracture(result["history"][0]) is True


def test_diagnostics_include_temp_video_hash_and_bytes():
    """Diagnostics must expose temp video hash/bytes from the clip builder."""
    video_meta = {"video_id": "v812", "duration": 60.0, "video_path": "v812.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 2

    responses = [
        {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.95},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("terminate", {"status": "no_fracture", "confidence": 0.95}),
    ])

    clip_builder = FakeClipBuilder()
    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=clip_builder,
        inference_client=FakeInferenceClient(responses),
    )

    result = agent.run()
    diag = result["history"][0]["result"]["diagnostics"]
    assert diag["temp_video_hash"] != ""
    assert diag["temp_video_bytes"] > 0
    assert diag["temp_video_manifest"] is not None
    assert len(diag["temp_video_manifest"]) > 0


# ---------------------------------------------------------------------------
# Sample range validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "sample_range",
    [
        [-10.0, 60.0],  # start < 0
        [0.0, 70.0],  # end > duration
        [60.0, 70.0],  # start >= duration
        [70.0, 60.0],  # start > end
        [30.0, 30.0],  # start == end
    ],
)
def test_invalid_sample_range_returns_validation_error(sample_range):
    """Runtime sample_range outside [0, duration] returns a validation error."""
    video_meta = {"video_id": "v900", "duration": 60.0, "video_path": "v900.mp4"}
    config = make_config()
    agent = IterativeAgent(
        llm_client=StaticLLM([]),
        video_meta=video_meta,
        config=config,
        inference_client=MagicMock(),
    )
    result = agent._execute_sample_and_infer(
        {"sample_range": sample_range, "prompt": "analyze"},
        round_idx=0,
    )
    assert result["ok"] is False
    error = result["validation_error"]
    assert error["code"] == "invalid_sample_range"
    assert error["field"] == "sample_range"


# ---------------------------------------------------------------------------
# Infrastructure failure regression
# ---------------------------------------------------------------------------
class FailingClipBuilder:
    """Clip builder that always raises, simulating sampling infrastructure failure."""

    def build_with_manifest(
        self,
        source_video: str,
        sample_range: list[float],
    ) -> ClipBuildResult:
        raise RuntimeError("sampling infrastructure failure")


def test_consecutive_sampling_failures_terminate_runner():
    video_meta = {"video_id": "v901", "duration": 60.0, "video_path": "v901.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 5

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 30.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [30.0, 60.0], "prompt": "analyze"}),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FailingClipBuilder(),
        inference_client=FakeInferenceClient([]),
    )

    result = agent.run()
    assert result["ok"] is False
    assert result["error"]["code"] == "consecutive_infra_failures"
    assert result["error"]["stage"] == "sampling"
    assert agent.infra_fail_count == 2
    assert agent.infra_terminated is True


# ---------------------------------------------------------------------------
# OSError isolation regression
# ---------------------------------------------------------------------------
def test_persist_diagnostics_oserror_isolated(monkeypatch, tmp_path: Path):
    """_persist_diagnostics OSError must not propagate from _execute_sample_and_infer."""
    video_meta = {"video_id": "v920", "duration": 60.0, "video_path": "v920.mp4"}
    config = make_config()

    def failing_write_text(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", failing_write_text)

    agent = IterativeAgent(
        llm_client=StaticLLM([]),
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient([
            {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.95},
        ]),
        work_dir=str(tmp_path),
    )

    result = agent._execute_sample_and_infer(
        {"sample_range": [0.0, 60.0], "prompt": "analyze"},
        round_idx=0,
    )
    # The round result itself must remain valid; only the side-effect write failed.
    assert result["ok"] is True
    assert result["model_output"]["has_fracture"] is False
    assert result["diagnostics"] is not None

    # No per-round diagnostics file should have been created.
    diag_dir = tmp_path / "data" / "08_runtime" / "diagnostics"
    assert not any(diag_dir.glob("v920_round_*_diagnostics.json"))


def test_persist_summary_oserror_isolated(monkeypatch, tmp_path: Path):
    """_persist_summary OSError must not propagate from run(); per-round diagnostics may succeed."""
    video_meta = {"video_id": "v921", "duration": 60.0, "video_path": "v921.mp4"}
    config = make_config()
    config["agent"]["max_rounds"] = 3

    original_write_text = Path.write_text

    def selective_failing_write_text(self, *args, **kwargs):
        if "diagnostics_summary.json" in str(self):
            raise OSError("summary disk full")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", selective_failing_write_text)

    responses = [
        {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.95},
        {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.95},
    ]

    llm = StaticLLM([
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("sample_and_infer", {"sample_range": [0.0, 60.0], "prompt": "analyze"}),
        ("terminate", {"status": "no_fracture", "confidence": 0.95}),
    ])

    agent = IterativeAgent(
        llm_client=llm,
        video_meta=video_meta,
        config=config,
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(responses),
        work_dir=str(tmp_path),
    )

    result = agent.run()
    assert result["status"] == "no_fracture"
    assert result["rounds"] == 2

    diag_dir = tmp_path / "data" / "08_runtime" / "diagnostics"
    # Per-round diagnostics should have been written successfully.
    round_files = list(diag_dir.glob("v921_round_*_diagnostics.json"))
    assert len(round_files) == 2
    # Summary must not exist because its write failed.
    assert not (diag_dir / "v921_diagnostics_summary.json").exists()
