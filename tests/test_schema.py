from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.schema import (
    FinalOutput,
    FractureType,
    LocationType,
    ModelOutput,
    RunnerError,
    RunnerResult,
    SampleAndInferDiagnostics,
    SampleAndInferResult,
    ToolSampleAndInfer,
    ToolTerminate,
    ValidationErrorInfo,
)


# ---------------------------------------------------------------------------
# ModelOutput: five legal combinations
# ---------------------------------------------------------------------------
def test_model_output_normal_fracture():
    output = ModelOutput(
        has_fracture=True,
        fracture_between=[17, 18],
        type=FractureType.TOUGH,
        location=LocationType.INSIDE,
        confidence=0.92,
    )
    data = output.model_dump()
    assert data["has_fracture"] is True
    assert data["fracture_between"] == [17, 18]
    assert data["type"] == "韧性断裂"
    assert data["location"] == "inside_gauge"
    assert data["confidence"] == pytest.approx(0.92)


@pytest.mark.parametrize("value", [1, 0, "true", "false"])
def test_model_output_rejects_non_boolean_has_fracture(value):
    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=value,
            fracture_between=None,
            type=FractureType.NO_FRACTURE,
            location=None,
            confidence=0.8,
        )


def test_model_output_no_fracture():
    output = ModelOutput(
        has_fracture=False,
        fracture_between=None,
        type=FractureType.NO_FRACTURE,
        location=None,
        confidence=0.95,
    )
    assert output.type == FractureType.NO_FRACTURE
    assert output.location is None


def test_model_output_not_clamped():
    output = ModelOutput(
        has_fracture=False,
        fracture_between=None,
        type=FractureType.NOT_CLAMPED,
        location=None,
        confidence=0.88,
    )
    assert output.type == FractureType.NOT_CLAMPED


def test_model_output_video_anomaly_unknown_presence():
    output = ModelOutput(
        has_fracture=None,
        fracture_between=None,
        type=FractureType.VIDEO_ABNORMAL,
        location=None,
        confidence=0.70,
    )
    assert output.has_fracture is None
    assert output.type == FractureType.VIDEO_ABNORMAL


def test_model_output_video_anomaly_unreliable_time():
    output = ModelOutput(
        has_fracture=True,
        fracture_between=None,
        type=FractureType.VIDEO_ABNORMAL,
        location=None,
        confidence=0.65,
    )
    assert output.has_fracture is True
    assert output.fracture_between is None


# ---------------------------------------------------------------------------
# ModelOutput: type closed set and illegal combinations
# ---------------------------------------------------------------------------
def test_model_output_accepts_string_enums():
    output = ModelOutput(
        has_fracture=False,
        fracture_between=None,
        type="未断裂",
        location=None,
        confidence=0.95,
    )
    assert output.type == FractureType.NO_FRACTURE


def test_model_output_rejects_invalid_type_for_fracture():
    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=True,
            fracture_between=[17, 18],
            type="未断裂",
            location=LocationType.INSIDE,
            confidence=0.92,
        )


def test_model_output_rejects_video_anomaly_with_fracture_between():
    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=True,
            fracture_between=[0, 1],
            type=FractureType.VIDEO_ABNORMAL,
            location=None,
            confidence=0.65,
        )


def test_model_output_rejects_no_fracture_with_location():
    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=False,
            fracture_between=None,
            type=FractureType.NO_FRACTURE,
            location="outside_gauge",
            confidence=0.88,
        )


def test_model_output_rejects_null_has_fracture_with_non_video_anomaly():
    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=None,
            fracture_between=None,
            type=FractureType.NO_FRACTURE,
            location=None,
            confidence=0.88,
        )


# ---------------------------------------------------------------------------
# ModelOutput: numeric and index validation
# ---------------------------------------------------------------------------
def test_model_output_rejects_confidence_out_of_range():
    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=True,
            fracture_between=[17, 18],
            type=FractureType.TOUGH,
            location=LocationType.INSIDE,
            confidence=1.5,
        )


def test_model_output_rejects_boolean_confidence():
    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=True,
            fracture_between=[17, 18],
            type=FractureType.TOUGH,
            location=LocationType.INSIDE,
            confidence=True,  # type: ignore[arg-type]
        )


def test_model_output_rejects_non_adjacent_fracture_between():
    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=True,
            fracture_between=[17, 19],
            type=FractureType.TOUGH,
            location=LocationType.INSIDE,
            confidence=0.92,
        )


def test_model_output_rejects_equal_fracture_between():
    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=True,
            fracture_between=[17, 17],
            type=FractureType.TOUGH,
            location=LocationType.INSIDE,
            confidence=0.92,
        )


def test_model_output_rejects_negative_fracture_between():
    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=True,
            fracture_between=[-1, 0],
            type=FractureType.TOUGH,
            location=LocationType.INSIDE,
            confidence=0.92,
        )


def test_model_output_rejects_boolean_indexes():
    with pytest.raises(ValidationError):
        ModelOutput(
            has_fracture=True,
            fracture_between=[True, False],  # type: ignore[list-item]
            type=FractureType.TOUGH,
            location=LocationType.INSIDE,
            confidence=0.92,
        )


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------
def test_tool_sample_and_infer_only_two_fields():
    tool = ToolSampleAndInfer(
        sample_range=[0.0, 500.0],
        prompt="请分析视频",
    )
    assert tool.sample_range == [0.0, 500.0]
    assert tool.prompt == "请分析视频"
    data = tool.model_dump()
    assert set(data.keys()) == {"sample_range", "prompt"}


def test_tool_sample_and_infer_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ToolSampleAndInfer(
            sample_range=[0.0, 500.0],
            prompt="请分析视频",
            num_frames=36,  # type: ignore[call-arg]
        )


def test_tool_sample_and_infer_rejects_prompt_over_4096():
    with pytest.raises(ValidationError):
        ToolSampleAndInfer(
            sample_range=[0.0, 500.0],
            prompt="x" * 4097,
        )


def test_tool_sample_and_infer_rejects_literal_video_marker():
    with pytest.raises(ValidationError):
        ToolSampleAndInfer(
            sample_range=[0.0, 500.0],
            prompt="请分析<video>视频",
        )


@pytest.mark.parametrize(
    "sample_range",
    [
        [10.0, 5.0],  # start >= end
        [5.0, 5.0],  # start == end
        [float("inf"), 10.0],  # non-finite start
        [0.0, float("nan")],  # non-finite end
    ],
)
def test_tool_sample_and_infer_rejects_invalid_range(sample_range):
    with pytest.raises(ValidationError):
        ToolSampleAndInfer(
            sample_range=sample_range,
            prompt="请分析视频",
        )


def test_tool_terminate_fracture_status():
    tool = ToolTerminate(
        status="fracture",
        fracture_type=FractureType.TOUGH,
        location=LocationType.INSIDE,
        confidence=0.79,
        evidence_rounds=[0, 1],
    )
    assert tool.status == "fracture"
    assert tool.unrecognized_reason is None


def test_tool_terminate_unrecognized_status():
    tool = ToolTerminate(
        status="unrecognized",
        unrecognized_reason="video_anomaly",
    )
    assert tool.status == "unrecognized"
    assert tool.confidence is None


def test_tool_terminate_no_fracture_status():
    tool = ToolTerminate(
        status="no_fracture",
        confidence=0.85,
    )
    assert tool.status == "no_fracture"


def test_tool_terminate_rejects_invalid_status():
    with pytest.raises(ValidationError):
        ToolTerminate(status="broken")


def test_tool_terminate_fracture_requires_evidence():
    with pytest.raises(ValidationError):
        ToolTerminate(
            status="fracture",
            fracture_type=FractureType.TOUGH,
            location=LocationType.INSIDE,
            confidence=0.79,
        )


# ---------------------------------------------------------------------------
# SampleAndInferResult and diagnostics
# ---------------------------------------------------------------------------
def test_sample_and_infer_result_compact():
    result = SampleAndInferResult(
        ok=True,
        sample_range=[143.9, 146.9],
        model_output={"has_fracture": True, "fracture_between": [17, 18]},
        inferred_time_range=[143.9, 146.9],
        attempts=1,
    )
    assert result.ok is True
    assert result.attempts == 1
    data = result.model_dump()
    assert set(data.keys()) == {
        "ok",
        "sample_range",
        "model_output",
        "inferred_time_range",
        "validation_error",
        "attempts",
    }


def test_sample_and_infer_diagnostics():
    diag = SampleAndInferDiagnostics(
        request_id="req-001",
        max_frames=8,
        sampled_frames=[{"index": 0, "timestamp": 1.0}],
    )
    assert diag.request_id == "req-001"


def test_validation_error_info():
    error = ValidationErrorInfo(code="invalid_json", message="bad json")
    assert error.code == "invalid_json"


# ---------------------------------------------------------------------------
# FinalOutput and RunnerResult
# ---------------------------------------------------------------------------
def test_final_output_fracture():
    output = FinalOutput(
        video_id="v001",
        status="fracture",
        time_range=[1.0, 2.0],
        fracture_type=FractureType.TOUGH,
        location=LocationType.INSIDE,
        confidence=0.92,
    )
    assert output.status == "fracture"


def test_final_output_no_fracture():
    output = FinalOutput(
        video_id="v001",
        status="no_fracture",
        confidence=0.95,
    )
    assert output.time_range is None
    assert output.fracture_type is None
    assert output.location is None
    assert output.unrecognized_reason is None


def test_final_output_unrecognized():
    output = FinalOutput(
        video_id="v001",
        status="unrecognized",
        unrecognized_reason="video_anomaly",
    )
    assert output.confidence is None


def test_tool_and_final_output_reject_unknown_unrecognized_reason():
    with pytest.raises(ValidationError):
        ToolTerminate(status="unrecognized", unrecognized_reason="arbitrary_reason")
    with pytest.raises(ValidationError):
        FinalOutput(
            video_id="v001",
            status="unrecognized",
            unrecognized_reason="arbitrary_reason",
        )


@pytest.mark.parametrize("value", [0, 1, "true"])
def test_result_envelopes_reject_non_boolean_ok(value):
    with pytest.raises(ValidationError):
        SampleAndInferResult(
            ok=value,
            sample_range=[0.0, 1.0],
            validation_error=ValidationErrorInfo(code="invalid", message="invalid"),
            attempts=1,
        )
    with pytest.raises(ValidationError):
        RunnerResult(
            ok=value,
            error=RunnerError(stage="internal", code="invalid", message="invalid"),
        )


def test_final_output_rejects_invalid_status():
    with pytest.raises(ValidationError):
        FinalOutput(
            video_id="v001",
            status="unknown",
            confidence=0.5,
        )


def test_runner_result_success():
    result = RunnerResult(
        ok=True,
        result=FinalOutput(
            video_id="v001",
            status="no_fracture",
            confidence=0.95,
        ),
    )
    assert result.ok is True
    assert result.error is None


def test_runner_result_failure():
    result = RunnerResult(
        ok=False,
        error=RunnerError(stage="inference_transport", code="timeout", message="connection timeout"),
    )
    assert result.ok is False
    assert result.result is None
