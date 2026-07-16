"""Pydantic models that formalize the model/agent interface contract.

See ``docs/PROJECT_PLAN.md`` for the authoritative Agent-side contract. This
module implements the model output, tool schemas and public result envelopes
used by the iterative localization pipeline.
"""

from __future__ import annotations

import math

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FractureType(StrEnum):
    """Fracture mode / anomaly class values allowed by the contract."""

    TOUGH = "韧性断裂"
    BRITTLE = "脆性断裂"
    INTERFACE_DEBOND = "界面脱粘"
    ROOT = "齐根断裂"
    EXPLOSIVE = "爆炸性断裂"
    MIXED = "半脆半韧断裂"
    INTERFACE_DEBOND_AND_ROOT = "界面脱粘、齐根断裂"
    NO_FRACTURE = "未断裂"
    NOT_CLAMPED = "未夹紧"
    VIDEO_ABNORMAL = "视频异常"


FRACTURE_CLASSES: set[str] = {
    FractureType.TOUGH,
    FractureType.BRITTLE,
    FractureType.INTERFACE_DEBOND,
    FractureType.ROOT,
    FractureType.EXPLOSIVE,
    FractureType.MIXED,
    FractureType.INTERFACE_DEBOND_AND_ROOT,
}

NON_FRACTURE_CLASSES: set[str] = {
    FractureType.NO_FRACTURE,
    FractureType.NOT_CLAMPED,
}

ALL_MODEL_OUTPUT_TYPES: set[str] = FRACTURE_CLASSES | NON_FRACTURE_CLASSES | {FractureType.VIDEO_ABNORMAL}

UNRECOGNIZED_REASONS: set[str] = {
    "video_anomaly",
    "not_clamped",
    "conflicting_results",
    "invalid_model_output",
    "insufficient_confidence",
    "incomplete_coverage",
    "max_rounds",
}


class LocationType(StrEnum):
    """Gauge-length location judgment."""

    INSIDE = "inside_gauge"
    OUTSIDE = "outside_gauge"


# ---------------------------------------------------------------------------
# v3 model output: exactly the four fields used during fine-tuning
# ---------------------------------------------------------------------------
class ModelOutput(BaseModel):
    """Single-round fine-tuned model output JSON schema.

    The object always contains exactly the four trained fields below.
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    has_fracture: bool | None
    fracture_between: list[int] | None = None
    type: FractureType
    location: str | None = None

    @field_validator("has_fracture", mode="before")
    @classmethod
    def _validate_has_fracture(cls, value: Any) -> Any:
        if value is not None and not isinstance(value, bool):
            raise ValueError("has_fracture must be a JSON boolean or null")
        return value

    @field_validator("fracture_between", mode="before")
    @classmethod
    def _reject_bool_indexes(cls, value: Any) -> Any:
        if isinstance(value, list) and any(
            isinstance(item, bool) or not isinstance(item, int) for item in value
        ):
            raise ValueError("fracture_between indexes must be JSON integers")
        return value

    @model_validator(mode="after")
    def _validate_five_legal_combinations(self) -> Self:
        # Combination 1: normal fracture with locatable boundary.
        if self.has_fracture is True and self.type in FRACTURE_CLASSES:
            if self.fracture_between is None:
                raise ValueError("fracture_between is required for a normal fracture prediction")
            if len(self.fracture_between) != 2:
                raise ValueError("fracture_between must contain exactly two integers [i, i+1]")
            i, j = self.fracture_between
            if j != i + 1 or i < 0:
                raise ValueError("fracture_between must be strictly adjacent [i, i+1] with i >= 0")
            if self.location not in {LocationType.INSIDE, LocationType.OUTSIDE}:
                raise ValueError(
                    "location must be inside_gauge or outside_gauge for a normal fracture prediction"
                )
            return self

        # Combination 5: video anomaly but fracture presence is confirmed.
        if self.has_fracture is True and self.type == FractureType.VIDEO_ABNORMAL:
            if self.fracture_between is not None:
                raise ValueError(
                    "fracture_between must be null for video anomaly with confirmed fracture"
                )
            if self.location is not None:
                raise ValueError("location must be null for video anomaly")
            return self

        # Combinations 2 & 3: confirmed no fracture / not clamped.
        if self.has_fracture is False:
            if self.fracture_between is not None:
                raise ValueError("fracture_between must be null when has_fracture is false")
            if self.type not in {FractureType.NO_FRACTURE, FractureType.NOT_CLAMPED}:
                raise ValueError(
                    "type must be 未断裂 or 未夹紧 when has_fracture is false, "
                    f"got {self.type}"
                )
            if self.location is not None:
                raise ValueError("location must be null when has_fracture is false")
            return self

        # Combination 4: video anomaly, fracture presence unknown.
        if self.has_fracture is None:
            if self.fracture_between is not None:
                raise ValueError("fracture_between must be null when has_fracture is null")
            if self.type != FractureType.VIDEO_ABNORMAL:
                raise ValueError(
                    "type must be 视频异常 when has_fracture is null, "
                    f"got {self.type}"
                )
            if self.location is not None:
                raise ValueError("location must be null when has_fracture is null")
            return self

        raise ValueError(f"illegal combination: has_fracture={self.has_fracture}, type={self.type}")


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------
class ToolSampleAndInfer(BaseModel):
    """Planner contract for a fixed, program-owned visual prompt."""

    model_config = ConfigDict(extra="forbid")

    sample_range: list[float] = Field(..., min_length=2, max_length=2)
    task_mode: Literal["analyze"] = "analyze"

    @model_validator(mode="before")
    @classmethod
    def _discard_legacy_prompt(cls, value: Any) -> Any:
        """Accept old recorded tool calls without forwarding their prompt."""
        if isinstance(value, dict) and "prompt" in value:
            value = dict(value)
            value.pop("prompt", None)
        return value

    @field_validator("sample_range", mode="before")
    @classmethod
    def _validate_sample_range(cls, value: Any) -> Any:
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("sample_range must contain exactly two floats")
        if any(
            isinstance(item, bool) or not isinstance(item, (int, float))
            for item in value
        ):
            raise ValueError("sample_range values must be JSON numbers")
        start, end = value
        if not math.isfinite(start) or not math.isfinite(end):
            raise ValueError("sample_range values must be finite floats")
        if not start < end:
            raise ValueError("sample_range must satisfy start < end")
        return value

class ToolTerminate(BaseModel):
    """Schema for the ``terminate`` tool (v3).

    The decision model proposes a final status, the semantic fields and the
    evidence rounds that support the proposal. The program later derives the
    concrete ``time_range`` and validates the proposal against the evidence
    threshold rules.
    """

    model_config = ConfigDict(extra="forbid")

    status: str = Field(
        description="只能是 fracture、no_fracture 或 unrecognized",
        json_schema_extra={"enum": ["fracture", "no_fracture", "unrecognized"]},
    )
    fracture_type: str | None = Field(
        default=None,
        description="status=fracture 时必填，且只能是七种中文断裂类别；其他 status 省略此字段",
        json_schema_extra={"enum": [str(item) for item in sorted(FRACTURE_CLASSES)] + [None]},
    )
    location: str | None = Field(
        default=None,
        description="status=fracture 时只能是 inside_gauge 或 outside_gauge；其他 status 省略此字段",
        json_schema_extra={"enum": ["inside_gauge", "outside_gauge", None]},
    )
    unrecognized_reason: str | None = Field(
        default=None,
        description="status=unrecognized 时必填合法原因；其他 status 省略此字段",
        json_schema_extra={"enum": sorted(UNRECOGNIZED_REASONS) + [None]},
    )
    evidence_rounds: list[int] | None = Field(
        default=None,
        description="仅 fracture 结论传入，值为引用的 evidence_index；其他 status 省略此字段",
    )

    @model_validator(mode="before")
    @classmethod
    def _discard_legacy_confidence(cls, value: Any) -> Any:
        """Accept recorded v2 tool calls without trusting Planner confidence."""
        if isinstance(value, dict) and "confidence" in value:
            value = dict(value)
            value.pop("confidence", None)
        return value

    @field_validator("evidence_rounds", mode="before")
    @classmethod
    def _validate_evidence_rounds(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, list) or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in value
        ):
            raise ValueError("evidence_rounds must contain non-negative integers")
        if len(value) != len(set(value)):
            raise ValueError("evidence_rounds must not contain duplicates")
        return value

    @model_validator(mode="after")
    def _validate_status(self) -> Self:
        valid_statuses = {"fracture", "no_fracture", "unrecognized"}
        if self.status not in valid_statuses:
            raise ValueError(f"status must be one of {valid_statuses}, got {self.status}")

        if self.status == "fracture":
            if self.fracture_type not in FRACTURE_CLASSES:
                raise ValueError("fracture_type must be one of the 7 fracture classes")
            if self.location not in {LocationType.INSIDE, LocationType.OUTSIDE}:
                raise ValueError("location must be inside_gauge or outside_gauge for fracture status")
            if self.unrecognized_reason is not None:
                raise ValueError("unrecognized_reason must be null for fracture status")
            if not self.evidence_rounds:
                raise ValueError("evidence_rounds is required for fracture status")

        elif self.status == "no_fracture":
            if self.fracture_type is not None:
                raise ValueError("fracture_type must be null for no_fracture status")
            if self.location is not None:
                raise ValueError("location must be null for no_fracture status")
            if self.unrecognized_reason is not None:
                raise ValueError("unrecognized_reason must be null for no_fracture status")

        else:  # unrecognized
            if self.unrecognized_reason not in UNRECOGNIZED_REASONS:
                raise ValueError(
                    f"unrecognized_reason must be one of {sorted(UNRECOGNIZED_REASONS)}"
                )
            if self.fracture_type is not None:
                raise ValueError("fracture_type must be null for unrecognized status")
            if self.location is not None:
                raise ValueError("location must be null for unrecognized status")
            if self.evidence_rounds is not None:
                raise ValueError("evidence_rounds must be null for unrecognized status")

        return self


# ---------------------------------------------------------------------------
# Tool results and diagnostics
# ---------------------------------------------------------------------------
class ValidationErrorInfo(BaseModel):
    """Stable validation error object exposed to the decision model."""

    code: str
    message: str
    field: str | None = None


class SampleAndInferResult(BaseModel):
    """Compact tool result visible to the decision model (v2).

    This object deliberately excludes temporary paths, full frame tables and
    raw HTTP payloads. Those details live in ``SampleAndInferDiagnostics``.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    sample_range: list[float] = Field(..., min_length=2, max_length=2)
    model_output: dict[str, Any] | None = None
    inferred_time_range: list[float] | None = Field(None, min_length=2, max_length=2)
    validation_error: ValidationErrorInfo | None = None
    attempts: int = Field(..., ge=1, le=3)

    @field_validator("ok", mode="before")
    @classmethod
    def _validate_ok(cls, value: Any) -> Any:
        if not isinstance(value, bool):
            raise ValueError("ok must be a JSON boolean")
        return value

    @field_validator("sample_range", "inferred_time_range", mode="before")
    @classmethod
    def _validate_ranges(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("time ranges must contain exactly two JSON numbers")
        if any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(item)
            for item in value
        ):
            raise ValueError("time ranges must contain finite JSON numbers")
        return value

    @field_validator("attempts", mode="before")
    @classmethod
    def _validate_attempts(cls, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("attempts must be a JSON integer")
        return value

    @model_validator(mode="after")
    def _validate_result_consistency(self) -> Self:
        if self.ok:
            if self.validation_error is not None:
                raise ValueError("validation_error must be null when ok is true")
        else:
            if self.model_output is not None:
                raise ValueError("model_output must be null when ok is false")
            if self.inferred_time_range is not None:
                raise ValueError("inferred_time_range must be null when ok is false")
            if self.validation_error is None:
                raise ValueError("validation_error is required when ok is false")
        return self


class SampleAndInferDiagnostics(BaseModel):
    """Internal diagnostics for a single ``sample_and_infer`` execution."""

    model_config = ConfigDict(extra="forbid")

    request_id: str | None = None
    processor_version: str | None = None
    max_frames: int | None = None
    sampled_frames: list[dict[str, Any]] | None = None
    deployment_manifest: dict[str, Any] | None = None
    temp_video_manifest: list[dict[str, Any]] | None = None
    internal_frame_range: list[int] | None = None
    temp_video_hash: str | None = None
    temp_video_bytes: int | None = None
    mime_type: str | None = None
    base64_length: int | None = None
    raw_http_response: dict[str, Any] | None = None
    transport_retries: int = 0
    correction_retries: int = 0
    elapsed_seconds: float | None = None
    error: ValidationErrorInfo | None = None
    video_anomaly_kind: str | None = None


class UserIntent(BaseModel):
    """Validated interpretation of a user's natural-language request."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["analyze_video", "explain_previous", "unsupported"] = "analyze_video"
    requested_fields: list[
        Literal[
            "has_fracture",
            "time_range",
            "type",
            "location",
            "confidence",
            "visual_evidence",
        ]
    ] = Field(default_factory=lambda: ["has_fracture"])
    wants_evidence: bool = False
    wants_confidence: bool = False
    response_detail: Literal["concise", "detailed"] = "concise"
    language: Literal["zh", "en"] = "zh"
    ambiguity: str | None = None

    @field_validator("requested_fields")
    @classmethod
    def _unique_requested_fields(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("requested_fields must not be empty")
        if len(value) != len(set(value)):
            raise ValueError("requested_fields must not contain duplicates")
        return value


class ConfidenceBreakdown(BaseModel):
    """Agent-level confidence values; never copied from MiniCPM output."""

    model_config = ConfigDict(extra="forbid")

    decision: float | None = Field(None, ge=0.0, le=1.0)
    localization: float | None = Field(None, ge=0.0, le=1.0)
    classification: float | None = Field(None, ge=0.0, le=1.0)
    overall: float | None = Field(None, ge=0.0, le=1.0)
    evidence_level: Literal["high", "medium", "low", "insufficient"] = "insufficient"
    calibration_version: str | None = None


class VisualEvidenceReference(BaseModel):
    """Trace pointer proving which clip and frames support an observation."""

    model_config = ConfigDict(extra="forbid")

    round: int = Field(..., ge=0)
    sample_range: list[float] = Field(..., min_length=2, max_length=2)
    frame_timestamps: list[float] = Field(default_factory=list)
    clip_hash: str = Field(..., min_length=1)
    request_id: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def _validate_trace(self) -> Self:
        start, end = self.sample_range
        if not math.isfinite(start) or not math.isfinite(end) or not start < end:
            raise ValueError("sample_range must contain finite increasing seconds")
        if not self.frame_timestamps:
            raise ValueError("frame_timestamps must not be empty")
        if any(not math.isfinite(value) for value in self.frame_timestamps):
            raise ValueError("frame_timestamps must be finite")
        if any(
            current <= previous
            for previous, current in zip(self.frame_timestamps, self.frame_timestamps[1:])
        ):
            raise ValueError("frame_timestamps must be strictly increasing")
        return self


class VisualEvidence(BaseModel):
    """User-safe evidence summary plus trace references."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["not_requested", "available", "unavailable"] = "not_requested"
    summary: str | None = None
    references: list[VisualEvidenceReference] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_evidence_state(self) -> Self:
        if self.status == "available" and not (self.summary and self.summary.strip()):
            raise ValueError("summary is required when visual evidence is available")
        if self.status == "available" and not self.references:
            raise ValueError("references are required when visual evidence is available")
        if self.status != "available" and self.summary is not None:
            raise ValueError("summary must be null unless visual evidence is available")
        if self.status != "available" and self.references:
            raise ValueError("references must be empty unless visual evidence is available")
        return self


# ---------------------------------------------------------------------------
# Final public result and Runner envelope
# ---------------------------------------------------------------------------
class FinalOutput(BaseModel):
    """Complete Agent conclusion before user-request projection (v4)."""

    model_config = ConfigDict(extra="forbid")

    video_id: str
    status: str
    time_range: list[float] | None = Field(None, min_length=2, max_length=2)
    fracture_type: str | None = None
    location: str | None = None
    confidence: ConfidenceBreakdown | None = None
    visual_evidence: VisualEvidence = Field(default_factory=VisualEvidence)
    unrecognized_reason: str | None = None

    @field_validator("time_range", mode="before")
    @classmethod
    def _validate_time_range_input(cls, value: Any) -> Any:
        if value is None:
            return value
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError("time_range must contain exactly two JSON numbers")
        if any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(item)
            for item in value
        ):
            raise ValueError("time_range values must be finite JSON numbers")
        return value

    @model_validator(mode="after")
    def _validate_public_result(self) -> Self:
        valid_statuses = {"fracture", "no_fracture", "unrecognized"}
        if self.status not in valid_statuses:
            raise ValueError(f"status must be one of {valid_statuses}, got {self.status}")

        if self.status == "fracture":
            if self.time_range is None:
                raise ValueError("time_range is required for fracture status")
            start, end = self.time_range
            if isinstance(start, bool) or isinstance(end, bool):
                raise ValueError("time_range values must be finite JSON numbers")
            if not math.isfinite(start) or not math.isfinite(end):
                raise ValueError("time_range values must be finite")
            if not start < end:
                raise ValueError("time_range must satisfy start < end")
            if end - start > 1.0 + 1e-9:
                raise ValueError("time_range width must be <= 1 second")
            if self.fracture_type not in FRACTURE_CLASSES:
                raise ValueError("fracture_type must be one of the 7 fracture classes")
            if self.location not in {LocationType.INSIDE, LocationType.OUTSIDE, "unknown"}:
                raise ValueError("location must be inside_gauge, outside_gauge or unknown")
            if self.unrecognized_reason is not None:
                raise ValueError("unrecognized_reason must be null for fracture status")

        elif self.status == "no_fracture":
            if self.time_range is not None:
                raise ValueError("time_range must be null for no_fracture status")
            if self.fracture_type is not None:
                raise ValueError("fracture_type must be null for no_fracture status")
            if self.location is not None:
                raise ValueError("location must be null for no_fracture status")
            if self.unrecognized_reason is not None:
                raise ValueError("unrecognized_reason must be null for no_fracture status")

        else:  # unrecognized
            if self.unrecognized_reason not in UNRECOGNIZED_REASONS:
                raise ValueError(
                    f"unrecognized_reason must be one of {sorted(UNRECOGNIZED_REASONS)}"
                )
            if self.time_range is not None:
                raise ValueError("time_range must be null for unrecognized status")
            if self.fracture_type is not None:
                raise ValueError("fracture_type must be null for unrecognized status")
            if self.location is not None:
                raise ValueError("location must be null for unrecognized status")
            if self.confidence is not None:
                raise ValueError("confidence must be null for unrecognized status")
        return self


class RunnerError(BaseModel):
    """Structured Runner failure envelope."""

    model_config = ConfigDict(extra="forbid")

    stage: Literal[
        "configuration",
        "input",
        "decision_backend",
        "inference_transport",
        "sampling",
        "internal",
    ]
    code: str
    message: str


class RunnerResult(BaseModel):
    """Runner execution envelope that separates success from infrastructure failure.

    Enforces mutual exclusion:
    - ``ok=True``  → ``result is not None and error is None``
    - ``ok=False`` → ``result is None and error is not None``
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    result: FinalOutput | None = None
    error: RunnerError | None = None

    @field_validator("ok", mode="before")
    @classmethod
    def _validate_ok(cls, value: Any) -> Any:
        if not isinstance(value, bool):
            raise ValueError("ok must be a JSON boolean")
        return value

    @model_validator(mode="after")
    def _validate_mutual_exclusion(self) -> Self:
        if self.ok:
            if self.result is None:
                raise ValueError("result is required when ok=True")
            if self.error is not None:
                raise ValueError("error must be None when ok=True")
        else:
            if self.result is not None:
                raise ValueError("result must be None when ok=False")
            if self.error is None:
                raise ValueError("error is required when ok=False")
        return self

    # ------------------------------------------------------------------
    # Dict-like access for backward compatibility
    # ------------------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        """Delegated item access: first top-level, then result/error fields."""
        if key in ("ok", "result", "error"):
            return getattr(self, key)
        if self.ok and self.result is not None:
            result_dict = self.result.model_dump()
            if key in result_dict:
                return result_dict[key]
        if not self.ok and self.error is not None:
            error_dict = self.error.model_dump()
            if key in error_dict:
                return error_dict[key]
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        """Dict-like get with default fallback."""
        try:
            return self[key]
        except KeyError:
            return default
