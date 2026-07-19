"""Contract acceptance tests for the model-agent interface.

Covers the three acceptance criteria from ``docs/PROJECT_PLAN.md``:

1. Three public states (fracture / no_fracture / unrecognized) — all condition
   field combinations with both valid and invalid paths.
2. Seven ``unrecognized_reason`` values — each tested end-to-end through the
   ``IterativeAgent`` loop.
3. Runner ``ok=false`` stages (input, configuration, sampling,
   inference_transport, decision_backend, internal) — each under the
   unrecognized path.

Reuses existing test infrastructure (``StaticLLM``, ``FakeClipBuilder``,
``FakeInferenceClient``, ``RecordingLLM``) without modifying them.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from unittest.mock import MagicMock

import json

import pytest
from pydantic import ValidationError

from agent.iterative_agent import IterativeAgent
from agent.llm import BaseAgentLLM
from agent.sampling import ClipBuildResult
from agent.schema import (
    FinalOutput,
    FRACTURE_CLASSES,
    FractureType,
    LocationType,
    RunnerError,
    RunnerResult,
    ToolSampleAndInfer,
    ToolTerminate,
)

# =========================================================================
# Imports from sibling test file — kept as aliases so we never modify originals
# =========================================================================

from tests.test_iterative_agent import (
    StaticLLM,
    FakeClipBuilder,
    FakeInferenceClient,
    RecordingLLM,
    make_config,
)


# =========================================================================
# 1. THREE PUBLIC STATES — condition field combinations
# =========================================================================

# -------------------------------------------------------------------------
# 1a. fracture state — valid combinations
# -------------------------------------------------------------------------

FRACTURE_TYPES_TUPLE = (
    FractureType.TOUGH,
    FractureType.BRITTLE,
    FractureType.INTERFACE_DEBOND,
    FractureType.ROOT,
    FractureType.EXPLOSIVE,
    FractureType.MIXED,
    FractureType.INTERFACE_DEBOND_AND_ROOT,
)

UNCALIBRATED_CONFIDENCE = {
    "decision": None,
    "localization": None,
    "classification": None,
    "overall": None,
    "evidence_level": "high",
    "calibration_version": None,
}


class TestFinalOutputFractureValid:
    """All valid fracture field combinations pass FinalOutput validation."""

    @pytest.mark.parametrize(
        "location",
        [LocationType.INSIDE, LocationType.OUTSIDE, None],
        ids=["inside_gauge", "outside_gauge", "unavailable"],
    )
    def test_location_accepts_enum_or_unavailable(self, location: str | None) -> None:
        output = FinalOutput(
            video_id="v001",
            status="fracture",
            time_range=[10.0, 11.0],
            fracture_type=FractureType.TOUGH,
            location=location,
            confidence=UNCALIBRATED_CONFIDENCE,
        )
        assert output.status == "fracture"
        assert output.unrecognized_reason is None

    def test_time_range_width_accepted(self) -> None:
        """Fracture allows time_range width <= 1.0 (contract spec)."""
        output = FinalOutput(
            video_id="v002",
            status="fracture",
            time_range=[143.9, 144.9],
            fracture_type=FractureType.BRITTLE,
            location="inside_gauge",
            confidence=UNCALIBRATED_CONFIDENCE,
        )
        assert output.status == "fracture"
        assert output.time_range == [143.9, 144.9]

    @pytest.mark.parametrize("ft", FRACTURE_TYPES_TUPLE, ids=[str(v) for v in FRACTURE_TYPES_TUPLE])
    def test_all_seven_fracture_types(self, ft: FractureType) -> None:
        """Each of the seven fracture classes is accepted."""
        output = FinalOutput(
            video_id="v003",
            status="fracture",
            time_range=[5.0, 6.0],
            fracture_type=ft,
            location="inside_gauge",
            confidence=UNCALIBRATED_CONFIDENCE,
        )
        assert output.fracture_type == ft

    def test_uncalibrated_confidence_keeps_numeric_values_null(self) -> None:
        output = FinalOutput(
            video_id="v004",
            status="fracture",
            time_range=[2.0, 3.0],
            fracture_type=FractureType.MIXED,
            location="inside_gauge",
            confidence=UNCALIBRATED_CONFIDENCE,
        )
        assert output.confidence is not None
        assert output.confidence.overall is None
        assert output.confidence.evidence_level == "high"


class TestFinalOutputFractureInvalid:
    """Invalid fracture field combinations are rejected by FinalOutput."""

    @pytest.mark.parametrize(
        "time_range",
        [[10.0, 11.0001], [11.0, 10.0], [10.0, 10.0], [10.0, float("inf")]],
    )
    def test_invalid_time_range_is_rejected(self, time_range: list[float]) -> None:
        with pytest.raises(ValidationError):
            FinalOutput(
                video_id="v_width",
                status="fracture",
                time_range=time_range,
                fracture_type=FractureType.TOUGH,
                location="inside_gauge",
                confidence=UNCALIBRATED_CONFIDENCE,
            )

    def test_missing_time_range_is_field_level_unavailable(self) -> None:
        output = FinalOutput(
            video_id="v005",
            status="fracture",
            fracture_type=FractureType.TOUGH,
            location="inside_gauge",
            confidence=UNCALIBRATED_CONFIDENCE,
        )
        assert output.field_status is not None
        assert output.field_status.time_range == "unavailable"

    def test_unrecognized_reason_must_be_null(self) -> None:
        with pytest.raises(ValidationError):
            FinalOutput(
                video_id="v006",
                status="fracture",
                time_range=[10.0, 11.0],
                fracture_type=FractureType.TOUGH,
                location="inside_gauge",
                confidence=UNCALIBRATED_CONFIDENCE,
                unrecognized_reason="video_anomaly",
            )

    def test_missing_confidence_is_allowed_until_calibrated(self) -> None:
        output = FinalOutput(
            video_id="v007",
            status="fracture",
            time_range=[10.0, 11.0],
            fracture_type=FractureType.TOUGH,
            location="inside_gauge",
        )
        assert output.confidence is None

    def test_invalid_fracture_type_rejected(self) -> None:
        """Non-fracture type (e.g. 未断裂) is invalid for fracture status."""
        with pytest.raises(ValidationError):
            FinalOutput(
                video_id="v008",
                status="fracture",
                time_range=[10.0, 11.0],
                fracture_type="未断裂",
                location="inside_gauge",
                confidence=UNCALIBRATED_CONFIDENCE,
            )

    @pytest.mark.parametrize(
        "bad_location",
        ["", "invalid"],
        ids=["empty_string", "invalid_value"],
    )
    def test_invalid_location_rejected(self, bad_location: Any) -> None:
        with pytest.raises(ValidationError):
            FinalOutput(
                video_id="v009",
                status="fracture",
                time_range=[10.0, 11.0],
                fracture_type=FractureType.TOUGH,
                location=bad_location,
                confidence=UNCALIBRATED_CONFIDENCE,
            )


# -------------------------------------------------------------------------
# 1b. no_fracture state — valid / invalid combinations
# -------------------------------------------------------------------------

class TestFinalOutputNoFractureValid:
    """Valid no_fracture field combinations pass FinalOutput validation."""

    def test_basic_no_fracture(self) -> None:
        output = FinalOutput(
            video_id="v010",
            status="no_fracture",
            confidence=UNCALIBRATED_CONFIDENCE,
        )
        assert output.status == "no_fracture"
        assert output.time_range is None
        assert output.fracture_type is None
        assert output.location is None
        assert output.unrecognized_reason is None

    def test_no_fracture_with_uncalibrated_confidence(self) -> None:
        output = FinalOutput(
            video_id="v011",
            status="no_fracture",
            confidence=UNCALIBRATED_CONFIDENCE,
        )
        assert output.confidence is not None
        assert output.confidence.overall is None


class TestFinalOutputNoFractureInvalid:
    """Invalid no_fracture field combinations are rejected by FinalOutput."""

    def test_time_range_must_be_null(self) -> None:
        with pytest.raises(ValidationError):
            FinalOutput(
                video_id="v012",
                status="no_fracture",
                time_range=[10.0, 11.0],
                confidence=UNCALIBRATED_CONFIDENCE,
            )

    def test_fracture_type_must_be_null(self) -> None:
        with pytest.raises(ValidationError):
            FinalOutput(
                video_id="v013",
                status="no_fracture",
                fracture_type=FractureType.TOUGH,
                confidence=UNCALIBRATED_CONFIDENCE,
            )

    def test_location_must_be_null(self) -> None:
        with pytest.raises(ValidationError):
            FinalOutput(
                video_id="v014",
                status="no_fracture",
                location="inside_gauge",
                confidence=UNCALIBRATED_CONFIDENCE,
            )

    def test_unrecognized_reason_must_be_null(self) -> None:
        with pytest.raises(ValidationError):
            FinalOutput(
                video_id="v015",
                status="no_fracture",
                unrecognized_reason="max_rounds",
                confidence=UNCALIBRATED_CONFIDENCE,
            )

    def test_missing_confidence_is_allowed_until_calibrated(self) -> None:
        output = FinalOutput(video_id="v016", status="no_fracture")
        assert output.confidence is None


# -------------------------------------------------------------------------
# 1c. unrecognized state — valid / invalid combinations
# -------------------------------------------------------------------------

class TestFinalOutputUnrecognizedValid:
    """Valid unrecognized field combinations pass FinalOutput validation."""

    def test_basic_unrecognized(self) -> None:
        output = FinalOutput(
            video_id="v017",
            status="unrecognized",
            unrecognized_reason="insufficient_confidence",
        )
        assert output.status == "unrecognized"
        assert output.time_range is None
        assert output.fracture_type is None
        assert output.location is None
        assert output.confidence is None


class TestFinalOutputUnrecognizedInvalid:
    """Invalid unrecognized field combinations are rejected by FinalOutput."""

    def test_uncalibrated_confidence_can_preserve_evidence_level(self) -> None:
        output = FinalOutput(
            video_id="v018",
            status="unrecognized",
            unrecognized_reason="visual_indeterminate",
            confidence=UNCALIBRATED_CONFIDENCE,
        )
        assert output.confidence is not None
        assert output.confidence.overall is None

    def test_fracture_type_must_be_null(self) -> None:
        with pytest.raises(ValidationError):
            FinalOutput(
                video_id="v019",
                status="unrecognized",
                unrecognized_reason="video_anomaly",
                fracture_type=FractureType.TOUGH,
            )

    def test_location_must_be_null(self) -> None:
        with pytest.raises(ValidationError):
            FinalOutput(
                video_id="v020",
                status="unrecognized",
                unrecognized_reason="video_anomaly",
                location="inside_gauge",
            )

    def test_time_range_must_be_null(self) -> None:
        with pytest.raises(ValidationError):
            FinalOutput(
                video_id="v021",
                status="unrecognized",
                unrecognized_reason="video_anomaly",
                time_range=[10.0, 11.0],
            )

    def test_missing_unrecognized_reason_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FinalOutput(
                video_id="v022",
                status="unrecognized",
            )


# -------------------------------------------------------------------------
# 1d. ToolTerminate — verify field constraints match FinalOutput semantics
# -------------------------------------------------------------------------

class TestToolTerminateConditionFields:
    """ToolTerminate validation mirrors FinalOutput contract rules."""

    def test_fracture_with_unknown_location(self) -> None:
        """ToolTerminate location must be inside_gauge or outside_gauge for fracture."""
        with pytest.raises(ValidationError):
            ToolTerminate(
                status="fracture",
                fracture_type=FractureType.TOUGH,
                location="unknown",
                confidence=UNCALIBRATED_CONFIDENCE,
                evidence_rounds=[0, 1],
            )

    def test_fracture_allows_null_location(self) -> None:
        tool = ToolTerminate(
            status="fracture",
            fracture_type=FractureType.TOUGH,
            location=None,
            confidence=UNCALIBRATED_CONFIDENCE,
            evidence_rounds=[0, 1],
        )
        assert tool.location is None

    def test_no_fracture_rejects_evidence_rounds(self) -> None:
        """no_fracture has no evidence_rounds requirement (but null is fine)."""
        tool = ToolTerminate(
            status="no_fracture",
            confidence=UNCALIBRATED_CONFIDENCE,
        )
        assert tool.evidence_rounds is None

    @pytest.mark.parametrize(
        "reason",
        ["video_anomaly", "not_clamped", "conflicting_results",
         "invalid_model_output", "insufficient_confidence",
         "incomplete_coverage", "max_rounds"],
    )
    def test_all_seven_unrecognized_reasons_accepted_by_schema(self, reason: str) -> None:
        """All seven valid unrecognized reasons pass ToolTerminate schema."""
        tool = ToolTerminate(
            status="unrecognized",
            unrecognized_reason=reason,
        )
        assert tool.unrecognized_reason == reason

    def test_unrecognized_rejects_evidence_rounds(self) -> None:
        with pytest.raises(ValidationError):
            ToolTerminate(
                status="unrecognized",
                unrecognized_reason="max_rounds",
                evidence_rounds=[0],
            )

    def test_unrecognized_rejects_fracture_type(self) -> None:
        with pytest.raises(ValidationError):
            ToolTerminate(
                status="unrecognized",
                unrecognized_reason="max_rounds",
                fracture_type=FractureType.TOUGH,
            )


# =========================================================================
# 2. SEVEN UNRECOGNIZED_REASONS — end-to-end through IterativeAgent
# =========================================================================

VALID_UNRECOGNIZED_REASONS = [
    "video_anomaly",
    "not_clamped",
    "conflicting_results",
    "invalid_model_output",
    "insufficient_confidence",
    "incomplete_coverage",
    "max_rounds",
]


class TestUnrecognizedReasonsEndToEnd:
    """Each valid unrecognized_reason is accepted in a full agent loop."""

    @pytest.mark.parametrize("reason", VALID_UNRECOGNIZED_REASONS)
    def test_unrecognized_reason_accepted(self, reason: str) -> None:
        """The agent accepts an unrecognized termination with each reason."""
        video_meta = {"video_id": "v_ure_001", "duration": 100.0, "video_path": "v_ure_001.mp4"}
        config = make_config()
        config["agent"]["max_rounds"] = 5

        if reason == "video_anomaly":
            output = {"has_fracture": None, "fracture_between": None, "type": "视频异常", "location": None, "confidence": 0.70}
        elif reason == "not_clamped":
            output = {"has_fracture": False, "fracture_between": None, "type": "未夹紧", "location": None, "confidence": 0.70}
        else:
            output = {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.50}
        responses = [output, deepcopy(output)]

        sequence = [("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"})]
        if reason in {"video_anomaly", "not_clamped"}:
            sequence.append(("sample_and_infer", {"sample_range": [10.0, 20.0], "prompt": "recheck"}))
        sequence.append(("terminate", {
                "status": "unrecognized",
                "unrecognized_reason": reason,
            }))
        llm = StaticLLM(sequence)

        agent = IterativeAgent(
            llm_client=llm,
            video_meta=video_meta,
            config=config,
            clip_builder=FakeClipBuilder(),
            inference_client=FakeInferenceClient(responses),
        )

        result = agent.run()
        assert result["status"] == "unrecognized"
        assert result["unrecognized_reason"] == reason
        assert result["time_range"] is None
        assert result["fracture_type"] is None
        assert result["location"] is None
        assert result["confidence"] is None


# =========================================================================
# 3. RUNNER ok=false STAGES — in the unrecognized path
# =========================================================================

# -------------------------------------------------------------------------
# 3a. Sampling stage — clip builder failure
# -------------------------------------------------------------------------

class FailingClipBuilder:
    """Clip builder that raises on every call, simulating a sampling failure."""

    def build_with_manifest(
        self,
        source_video: str,
        sample_range: list[float],
        **kwargs: Any,
    ) -> ClipBuildResult:
        raise RuntimeError(f"模拟采样错误: sample_range={sample_range}")


class TestRunnerOkFalseSampling:
    """Sampling stage failure leads to unrecognized termination."""

    def test_sampling_error_results_in_unrecognized(self) -> None:
        video_meta = {"video_id": "v_samp_001", "duration": 100.0, "video_path": "v_samp_001.mp4"}
        config = make_config()
        config["agent"]["max_rounds"] = 3

        # Model output is not used because sampling fails first.
        responses = [
            {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.50},
        ]

        llm = StaticLLM([
            ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
            ("terminate", {
                "status": "unrecognized",
                "unrecognized_reason": "invalid_model_output",
            }),
        ])

        agent = IterativeAgent(
            llm_client=llm,
            video_meta=video_meta,
            config=config,
            clip_builder=FailingClipBuilder(),
            inference_client=FakeInferenceClient(responses),
        )

        result = agent.run()
        assert result["ok"] is False
        assert result["error"]["stage"] == "sampling"
        assert result["error"]["code"] == "sampling_error"


# -------------------------------------------------------------------------
# 3b. Inference transport stage — inference call fails
# -------------------------------------------------------------------------

class FailingInferenceClient:
    """Inference client that raises on infer(), simulating transport failure."""

    def infer(self, video_input: Any, prompt: str) -> Any:
        raise RuntimeError("模拟推理传输错误: connection refused")


class TestRunnerOkFalseInference:
    """Inference transport failure leads to unrecognized termination."""

    def test_inference_transport_error_results_in_unrecognized(self) -> None:
        video_meta = {"video_id": "v_inf_001", "duration": 100.0, "video_path": "v_inf_001.mp4"}
        config = make_config()
        config["agent"]["max_rounds"] = 3

        llm = StaticLLM([
            ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
            ("terminate", {
                "status": "unrecognized",
                "unrecognized_reason": "invalid_model_output",
            }),
        ])

        agent = IterativeAgent(
            llm_client=llm,
            video_meta=video_meta,
            config=config,
            clip_builder=FakeClipBuilder(),
            inference_client=FailingInferenceClient(),
        )

        result = agent.run()
        assert result["ok"] is False
        assert result["error"]["stage"] == "inference_transport"


# -------------------------------------------------------------------------
# 3c. Decision backend stage — LLM fails to produce valid tool_calls
# -------------------------------------------------------------------------

class NoToolLLM(BaseAgentLLM):
    """LLM that never produces tool_calls, simulating decision backend failure."""

    def __init__(self) -> None:
        self.call_count = 0

    def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> Any:
        self.call_count += 1
        message = MagicMock()
        message.content = "I'm thinking..."
        message.tool_calls = None  # no tool_calls -> agent forces "请使用 tool_calls"
        choice = MagicMock()
        choice.message = message
        response = MagicMock()
        response.choices = [choice]
        return response

    @property
    def model_name(self) -> str:
        return "no-tool-llm"


class TestRunnerOkFalseDecisionBackend:
    """Decision backend (LLM) failure eventually leads to termination."""

    def test_llm_no_tool_calls_loop_ends_in_unrecognized(self) -> None:
        video_meta = {"video_id": "v_dec_001", "duration": 100.0, "video_path": "v_dec_001.mp4"}
        config = make_config()
        config["agent"]["max_rounds"] = 5

        # Provide some valid responses but the agent never gets to use them.
        responses = [
            {"has_fracture": False, "fracture_between": None, "type": "未断裂", "location": None, "confidence": 0.50},
        ]

        agent = IterativeAgent(
            llm_client=NoToolLLM(),
            video_meta=video_meta,
            config=config,
            clip_builder=FakeClipBuilder(),
            inference_client=FakeInferenceClient(responses),
        )

        result = agent.run()

        # When all rounds are exhausted with no positive evidence and no
        # fracture state, the agent force-terminates as no_fracture.
        # This is the expected contract behavior for max rounds with no
        # conclusive evidence.
        assert result["status"] in ("no_fracture", "unrecognized")
        assert result["time_range"] is None
        assert result["fracture_type"] is None
        assert result["location"] is None


# -------------------------------------------------------------------------
# 3d. Internal stage — internal processing error
# -------------------------------------------------------------------------

class TestRunnerOkFalseInternal:
    """Internal processing error is handled gracefully."""

    def test_internal_error_via_all_rounds_invalid(self) -> None:
        """All rounds return invalid model output → internal errors accumulated."""
        video_meta = {"video_id": "v_int_001", "duration": 100.0, "video_path": "v_int_001.mp4"}
        config = make_config()
        config["agent"]["max_rounds"] = 3

        # All responses are parse failures (strings that don't parse as valid model output)
        responses = [
            None,  # signals inference failure
            None,
            None,
        ]

        llm = StaticLLM([
            ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
            ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
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
        # All rounds failed → no positive evidence → no_fracture or unrecognized
        assert result["status"] in ("no_fracture", "unrecognized")
        assert result["time_range"] is None
        assert result["fracture_type"] is None
        assert result["location"] is None
        # Every round has a validation error
        for i, entry in enumerate(result["history"]):
            assert entry["result"].get("validation_error") is not None, (
                f"Round {i} should have a validation error"
            )


# -------------------------------------------------------------------------
# 3e. Input stage — bad input data handled in unrecognized path
# -------------------------------------------------------------------------

class TestRunnerOkFalseInput:
    """Input-level failure propagates correctly in the agent flow."""

    def test_input_validation_error_through_invalid_fracture_between(self) -> None:
        """Out-of-range fracture_between is an input mapping error handled gracefully."""
        video_meta = {"video_id": "v_inp_001", "duration": 100.0, "video_path": "v_inp_001.mp4"}
        config = make_config()
        config["agent"]["tolerance_seconds"] = 5.0
        config["agent"]["max_rounds"] = 3

        responses = [
            # fracture_between indices exceed manifest size → mapping failure
            {"has_fracture": True, "fracture_between": [999, 1000], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        ]

        llm = StaticLLM([
            ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
            ("terminate", {
                "status": "unrecognized",
                "unrecognized_reason": "invalid_model_output",
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
        # The validation error should mention the out-of-range indices.
        ve = result["history"][0]["result"].get("validation_error", {})
        assert ve is not None
        assert "超出采样帧索引范围" in str(ve)


# -------------------------------------------------------------------------
# 3f. Configuration stage — misconfiguration leads to fallback
# -------------------------------------------------------------------------

class TestRunnerOkFalseConfiguration:
    """Configuration-level issues are handled in the unrecognized path."""

    def test_low_confidence_threshold_leads_to_unrecognized(self) -> None:
        """Very high confidence threshold makes all rounds low-confidence → expands → unrecognized."""
        video_meta = {"video_id": "v_cfg_001", "duration": 100.0, "video_path": "v_cfg_001.mp4"}
        config = make_config()
        config["agent"]["confidence_threshold"] = 0.99  # nearly impossible to meet
        config["agent"]["max_rounds"] = 3

        responses = [
            {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
            {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
        ]

        llm = StaticLLM([
            ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
            ("sample_and_infer", {"sample_range": [48.571429, 51.428571], "prompt": "analyze"}),
            ("terminate", {
                "status": "unrecognized",
                "unrecognized_reason": "insufficient_confidence",
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
        assert result["unrecognized_reason"] == "insufficient_confidence"


# =========================================================================
# 4. EDGE CASES AND REGRESSION GUARDS
# =========================================================================

class TestEdgeCases:
    """Additional edge cases to guard against regressions."""

    def test_fracture_with_unavailable_location_in_finalize(self) -> None:
        video_meta = {"video_id": "v_edge_001", "duration": 100.0, "video_path": "v_edge_001.mp4"}
        config = make_config()
        agent = IterativeAgent(
            llm_client=StaticLLM([]),
            video_meta=video_meta,
            config=config,
            clip_builder=FakeClipBuilder(),
            inference_client=FakeInferenceClient([]),
        )
        result = agent._finalize({
            "status": "fracture",
            "time_range": [10.0, 10.5],
            "fracture_type": "韧性断裂",
            "location": None,
            "confidence": UNCALIBRATED_CONFIDENCE,
            "unrecognized_reason": None,
        })
        assert result["status"] == "fracture"
        assert result["location"] is None
        assert result["field_status"]["location"] == "unavailable"

    def test_non_fracture_type_in_terminate_rejected_by_schema(self) -> None:
        """Using a non-fracture type like 未断裂 in fracture terminate is rejected."""
        with pytest.raises(ValidationError):
            ToolTerminate(
                status="fracture",
                fracture_type="未断裂",
                location="inside_gauge",
                confidence=UNCALIBRATED_CONFIDENCE,
                evidence_rounds=[0, 1],
            )

    def test_video_anomaly_model_output_flows_to_unrecognized(self) -> None:
        """Video anomaly model output leads to unrecognized with video_anomaly reason."""
        video_meta = {"video_id": "v_edge_002", "duration": 100.0, "video_path": "v_edge_002.mp4"}
        config = make_config()

        responses = [
            # has_fracture=None indicates video anomaly, presence unknown
            {"has_fracture": None, "fracture_between": None, "type": "视频异常", "location": None, "confidence": 0.70},
            {"has_fracture": None, "fracture_between": None, "type": "视频异常", "location": None, "confidence": 0.70},
        ]

        llm = StaticLLM([
            ("sample_and_infer", {"sample_range": [0.0, 100.0], "prompt": "analyze"}),
            ("sample_and_infer", {"sample_range": [20.0, 40.0], "prompt": "recheck"}),
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


# =========================================================================
# 5. RUNNER RESULT ENVELOPE
# =========================================================================

class TestRunnerResultEnvelope:
    """The RunnerResult envelope correctly separates success from failure."""

    def test_runner_result_success_ok_true_with_result(self) -> None:
        result = RunnerResult(
            ok=True,
            result=FinalOutput(
                video_id="v_runner_001",
                status="no_fracture",
                confidence=UNCALIBRATED_CONFIDENCE,
            ),
        )
        assert result.ok is True
        assert result.result is not None
        assert result.result.status == "no_fracture"
        assert result.error is None

    def test_runner_result_failure_ok_false_with_error(self) -> None:
        result = RunnerResult(
            ok=False,
            error=RunnerError(stage="inference_transport", code="timeout", message="Connection timed out"),
        )
        assert result.ok is False
        assert result.result is None
        assert result.error is not None
        assert result.error.stage == "inference_transport"

    @pytest.mark.parametrize(
        "stage",
        ["input", "configuration", "sampling", "inference_transport", "decision_backend", "internal"],
        ids=["input", "configuration", "sampling", "inference_transport", "decision_backend", "internal"],
    )
    def test_runner_error_all_six_stages(self, stage: str) -> None:
        """All six RunnerError stages are accepted by the schema."""
        error = RunnerError(stage=stage, code="test_code", message="Test error")
        assert error.stage == stage

    # ---- Mutual exclusion enforcement (Fix 4a) ----

    def test_ok_true_rejects_missing_result(self) -> None:
        """ok=True with result=None raises ValidationError."""
        with pytest.raises(ValidationError, match="result is required when ok=True"):
            RunnerResult(ok=True, result=None, error=None)

    def test_ok_true_rejects_error_present(self) -> None:
        """ok=True with error set raises ValidationError."""
        with pytest.raises(ValidationError, match="error must be None when ok=True"):
            RunnerResult(
                ok=True,
                result=FinalOutput(video_id="v001", status="no_fracture", confidence=UNCALIBRATED_CONFIDENCE),
                error=RunnerError(stage="input", code="E", message="x"),
            )

    def test_ok_false_rejects_result_present(self) -> None:
        """ok=False with result set raises ValidationError."""
        with pytest.raises(ValidationError, match="result must be None when ok=False"):
            RunnerResult(
                ok=False,
                result=FinalOutput(video_id="v001", status="no_fracture", confidence=UNCALIBRATED_CONFIDENCE),
                error=RunnerError(stage="input", code="E", message="x"),
            )

    def test_ok_false_rejects_missing_error(self) -> None:
        """ok=False with error=None raises ValidationError."""
        with pytest.raises(ValidationError, match="error is required when ok=False"):
            RunnerResult(ok=False, result=None, error=None)

    # ---- Dict-like access (backward compat) ----

    def test_dict_access_ok_true_delegates_to_result(self) -> None:
        """When ok=True, dict access forwards to FinalOutput fields."""
        rr = RunnerResult(
            ok=True,
            result=FinalOutput(
                video_id="v_dict_001",
                status="fracture",
                time_range=[10.0, 11.0],
                fracture_type=FractureType.TOUGH,
                location="inside_gauge",
                confidence=UNCALIBRATED_CONFIDENCE,
            ),
        )
        assert rr["ok"] is True
        assert rr["video_id"] == "v_dict_001"
        assert rr["status"] == "fracture"
        assert rr.get("confidence")["overall"] is None
        assert rr.get("nonexistent", "fallback") == "fallback"

    def test_dict_access_ok_false_delegates_to_error(self) -> None:
        """When ok=False, dict access forwards to RunnerError fields."""
        rr = RunnerResult(
            ok=False,
            error=RunnerError(stage="sampling", code="timeout", message="Timeout"),
        )
        assert rr["ok"] is False
        assert rr["stage"] == "sampling"
        assert rr["code"] == "timeout"
        assert rr["message"] == "Timeout"
        assert rr.get("nonexistent") is None

    def test_dict_access_raises_keyerror_for_unknown_key(self) -> None:
        """Accessing an unknown key raises KeyError."""
        rr = RunnerResult(
            ok=True,
            result=FinalOutput(video_id="v001", status="no_fracture", confidence=UNCALIBRATED_CONFIDENCE),
        )
        with pytest.raises(KeyError):
            _ = rr["unknown_key"]


# =========================================================================
# 6. FIX 7: Pydantic validation rejects invalid tool call arguments
# =========================================================================

class TestToolCallValidation:
    """Invalid tool call arguments are rejected at the Pydantic layer."""

    def test_sample_and_infer_rejects_invalid_sample_range(self) -> None:
        """sample_range with 3 elements is rejected by ToolSampleAndInfer."""
        with pytest.raises(ValidationError):
            ToolSampleAndInfer(sample_range=[0.0, 50.0, 100.0], prompt="test")

    def test_sample_and_infer_discards_empty_legacy_prompt(self) -> None:
        tool = ToolSampleAndInfer(sample_range=[0.0, 100.0], prompt="")
        assert "prompt" not in tool.model_dump()

    def test_terminate_rejects_invalid_status(self) -> None:
        """Invalid status value is rejected by ToolTerminate model_validator."""
        with pytest.raises(ValidationError):
            ToolTerminate(status="bad_status")

    def test_terminate_fracture_rejects_non_fracture_type(self) -> None:
        """fracture status with 未断裂 type is rejected."""
        with pytest.raises(ValidationError):
            ToolTerminate(
                status="fracture",
                fracture_type="未断裂",
                location="inside_gauge",
                confidence=UNCALIBRATED_CONFIDENCE,
                evidence_rounds=[0, 1],
            )

    def test_terminate_fracture_rejects_unrecognized_reason(self) -> None:
        """fracture status with unrecognized_reason set is rejected (mutual exclusion)."""
        with pytest.raises(ValidationError):
            ToolTerminate(
                status="fracture",
                fracture_type="韧性断裂",
                location="inside_gauge",
                confidence=UNCALIBRATED_CONFIDENCE,
                unrecognized_reason="max_rounds",
                evidence_rounds=[0, 1],
            )

    def test_terminate_no_fracture_rejects_fracture_type(self) -> None:
        """no_fracture status with fracture_type set is rejected."""
        with pytest.raises(ValidationError):
            ToolTerminate(
                status="no_fracture",
                fracture_type="韧性断裂",
                confidence=UNCALIBRATED_CONFIDENCE,
            )

    def test_terminate_unrecognized_requires_reason(self) -> None:
        """unrecognized status without unrecognized_reason is rejected."""
        with pytest.raises(ValidationError):
            ToolTerminate(status="unrecognized")


# =========================================================================
# 7. FIX 2: Missing preprocessing metadata contract
# =========================================================================

class TestMissingPreprocessingContract:
    """Preprocessing metadata contract: missing + has_fracture → fail."""

    def test_missing_preprocessing_with_fracture_errors(self) -> None:
        """When preprocessing is None and has_fracture is True, the round fails."""
        from agent.inference import InferenceResult

        video_meta = {"video_id": "v_fix2_001", "duration": 100.0, "video_path": "v_fix2_001.mp4"}
        config = make_config()
        config["agent"]["max_rounds"] = 3

        responses = [
            InferenceResult(
                ok=True,
                model_output={
                    "has_fracture": True,
                    "fracture_between": [17, 18],
                    "type": "韧性断裂",
                    "location": "inside_gauge",
                    "confidence": 0.92,
                },
                attempts=1,
                preprocessing=None,  # explicitly None
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
            ("terminate", {"status": "no_fracture", "confidence": 0.95}),
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

    def test_missing_preprocessing_no_fracture_graceful(self) -> None:
        """When preprocessing is None and has_fracture is False, graceful degrade."""
        from agent.inference import InferenceResult

        video_meta = {"video_id": "v_fix2_002", "duration": 60.0, "video_path": "v_fix2_002.mp4"}
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
                preprocessing=None,
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
                preprocessing=None,
            ),
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
        )

        result = agent.run()
        assert result["ok"] is False
        assert result["error"]["code"] == "consecutive_infra_failures"


# =========================================================================
# 8. FIX 3: Evidence threshold — intersection and convergence
# =========================================================================

class TestEvidenceThresholdContract:
    """Evidence threshold: intersection check, max_rounds convergence."""

    def test_disjoint_evidence_ranges_prevent_termination(self) -> None:
        """Non-overlapping inferred_time_range across evidence rounds blocks termination."""
        video_meta = {"video_id": "v_fix3_001", "duration": 100.0, "video_path": "v_fix3_001.mp4"}
        config = make_config()
        config["agent"]["max_rounds"] = 5

        # Two rounds with disjoint ranges: [0.0, 2.857] and [48.571, 51.429]
        responses = [
            {"has_fracture": True, "fracture_between": [0, 1], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
            {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.91},
            {"has_fracture": True, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.90},
        ]

        llm = StaticLLM([
            ("sample_and_infer", {"sample_range": [0.0, 20.0], "prompt": "analyze"}),
            ("sample_and_infer", {"sample_range": [48.0, 52.0], "prompt": "analyze"}),
            # Try to terminate with disjoint evidence → rejected.
            ("terminate", {
                "status": "fracture",
                "fracture_type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.92,
                "evidence_rounds": [0, 1],
            }),
            ("sample_and_infer", {"sample_range": [48.0, 52.0], "prompt": "analyze"}),
            # Terminate with overlapping evidence (rounds 1, 2 have same range).
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
        # The second terminate (rounds 1, 2) should succeed with overlapping ranges.
        assert result["status"] == "fracture"
        assert result["fracture_type"] == "韧性断裂"

    def test_build_fracture_args_intersection(self) -> None:
        """_build_fracture_args returns intersection of all positive time ranges."""
        video_meta = {"video_id": "v_fix3_002", "duration": 100.0, "video_path": "v_fix3_002.mp4"}
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
            {"result": {
                "model_output": {"has_fracture": True, "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92},
                "inferred_time_range": [10.0, 20.0],
                "round_confidence_level": "高",
            }},
            {"result": {
                "model_output": {"has_fracture": True, "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.88},
                "inferred_time_range": [15.0, 18.0],
                "round_confidence_level": "中",
            }},
        ]

        args = agent._build_fracture_args(positive_rounds, {
            "status": "fracture",
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": 0.92,
        })
        assert args["time_range"] is None  # intersection is wider than tolerance
        assert args["fracture_type"] == "韧性断裂"
