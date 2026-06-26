"""Meta-Agent iterative controller.

Implements the deterministic state machine described in
``docs/IMPLEMENTATIONS/model-agent-contract.md`` section 3.3, migrated to the
v2 ``ToolSampleAndInfer`` / v3 ``ToolTerminate`` / ``FinalOutput`` contract.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from agent.inference import (
    InferenceClient,
    InferenceResult,
    LlamaFactoryInferenceClient,
    MockInferenceClient,
    _validate_preprocessing_meta,
)
from agent.llm import BaseAgentLLM

from agent.prompts import (
    META_AGENT_SYSTEM_PROMPT,
    build_meta_agent_user_context,
    build_sample_and_infer_prompt,
)
from agent.sampling import ClipBuildResult, FfmpegVideoClipBuilder, VideoClipBuilder
from agent.schema import (
    FinalOutput,
    FRACTURE_CLASSES,
    FractureType,
    LocationType,
    RunnerError,
    RunnerResult,
    SampleAndInferDiagnostics,
    SampleAndInferResult,
    ToolSampleAndInfer,
    ToolTerminate,
    ValidationErrorInfo,
)


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool schemas for Native Function Calling
# ---------------------------------------------------------------------------
TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "sample_and_infer",
            "description": "在指定时间区间内采样视频帧，调用微调模型（MiniCPM-V）进行推理。源视频由 Runner 上下文绑定，模型处理器最多选择 8 帧；不允许通过本工具指定帧数、帧率或采样策略。",
            "parameters": ToolSampleAndInfer.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "terminate",
            "description": "终止迭代，返回最终分析结果。程序从证据轮次派生 time_range 并执行终止门槛校验。",
            "parameters": ToolTerminate.model_json_schema(),
        },
    },
]

# ---------------------------------------------------------------------------
# Internal confidence helpers
# ---------------------------------------------------------------------------
def _confidence_to_level(confidence: float) -> str:
    """Map a numeric confidence to the four-level scale."""
    if confidence >= 0.90:
        return "高"
    if confidence >= 0.70:
        return "中"
    if confidence >= 0.50:
        return "低"
    return "不可信"


# ---------------------------------------------------------------------------
# IterativeAgent
# ---------------------------------------------------------------------------
class IterativeAgent:
    """Iterative frame-interval localization agent.

    The agent drives a Meta-Agent LLM through Native Function Calling.  State
    transitions, candidate interval updates, conflict handling and termination
    are enforced by this deterministic code layer, not delegated to the LLM.
    """

    def __init__(
        self,
        llm_client: BaseAgentLLM,
        video_meta: dict[str, Any],
        config: dict[str, Any],
        clip_builder: VideoClipBuilder | None = None,
        inference_client: InferenceClient | None = None,
        event_callback: Callable[[dict], None] | None = None,
        work_dir: str | Path | None = None,
    ) -> None:
        self.llm = llm_client
        self.video_meta = video_meta
        self.config = config
        self.history: list[dict[str, Any]] = []

        agent_cfg = config.get("agent", {})
        self.max_rounds = agent_cfg.get("max_rounds", 10)
        self.tolerance = agent_cfg.get("tolerance_seconds", 1.0)
        self.confidence_threshold = agent_cfg.get("confidence_threshold", 0.5)
        self.max_low_conf_rounds = agent_cfg.get("max_low_conf_rounds", 2)
        self.temperature = agent_cfg.get("temperature", 0.7)

        self.state = "INITIAL"
        duration = video_meta.get("duration", 0.0)
        self.candidate: list[float] = [0.0, duration]
        self.no_fracture_count = 0
        self.low_conf_count = 0
        self.conflict_count = 0
        self.focus_miss_count = 0
        self.infra_fail_count = 0
        self.infra_terminated = False
        self.last_round_confidence_level = "不可信"
        self.best_positive_round: dict[str, Any] | None = None
        self.coverage_index = 0
        self.pending_recheck_range: list[float] | None = None

        self.clip_builder = clip_builder or FfmpegVideoClipBuilder()
        self.inference_client = inference_client or self._default_inference_client()
        self.event_callback = event_callback
        self.work_dir = work_dir

    # ------------------------------------------------------------------
    # Event emission
    # ------------------------------------------------------------------
    def _emit(self, event_type: str, **payload: Any) -> None:
        """Emit an event to the optional UI callback."""
        if self.event_callback is None:
            return
        event: dict[str, Any] = {
            "event_type": event_type,
            "video_id": self.video_meta.get("video_id", "unknown"),
            **payload,
        }
        self.event_callback(event)

    @staticmethod
    def _to_json_value(value: Any) -> Any:
        """Convert a Pydantic model to a JSON-serializable dict if needed."""
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        return value

    # ------------------------------------------------------------------
    # Diagnostics persistence
    # ------------------------------------------------------------------
    def _diagnostics_dir(self) -> Path:
        """Return the runtime diagnostics directory for this agent run."""
        if self.work_dir is not None:
            return Path(self.work_dir) / "data" / "08_runtime" / "diagnostics"
        return Path("data/08_runtime/diagnostics")

    def _persist_diagnostics(
        self, round_idx: int, diagnostics: SampleAndInferDiagnostics
    ) -> None:
        """Persist one round's diagnostics to a JSON file."""
        try:
            d = self._diagnostics_dir()
            d.mkdir(parents=True, exist_ok=True)
            video_id = self.video_meta.get("video_id", "unknown")
            path = d / f"{video_id}_round_{round_idx:04d}_diagnostics.json"
            path.write_text(
                diagnostics.model_dump_json(indent=2, exclude_none=True),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to persist diagnostics: %s", exc)

    def _persist_summary(self, result: dict[str, Any]) -> None:
        """Persist the public result plus rounds/history as a summary JSON."""
        try:
            d = self._diagnostics_dir()
            d.mkdir(parents=True, exist_ok=True)
            video_id = result.get("video_id", self.video_meta.get("video_id", "unknown"))
            path = d / f"{video_id}_diagnostics_summary.json"
            public_fields = {
                "video_id",
                "status",
                "time_range",
                "fracture_type",
                "location",
                "confidence",
                "unrecognized_reason",
                "rounds",
                "history",
            }
            summary = {k: v for k, v in result.items() if k in public_fields}
            # Redact local temporary video paths from the persisted history; the
            # in-memory result keeps the original path for runtime diagnostics.
            if "history" in summary:
                summary["history"] = deepcopy(summary["history"])
                for entry in summary["history"]:
                    entry_result = entry.get("result")
                    if (
                        isinstance(entry_result, dict)
                        and isinstance(entry_result.get("model_video_path"), str)
                        and entry_result["model_video_path"]
                    ):
                        entry_result["model_video_path"] = "[REDACTED]"
            path.write_text(
                json.dumps(summary, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("Failed to persist summary: %s", exc)

    def _build_round_diagnostics(
        self,
        result: dict[str, Any],
        clip_result: ClipBuildResult | None,
        inference_result: InferenceResult | None,
        elapsed_seconds: float,
    ) -> SampleAndInferDiagnostics:
        """Build a ``SampleAndInferDiagnostics`` from a round's artifacts.

        Fields populated by ``inference.py`` are reused when available; the
        agent layer overwrites ``internal_frame_range``, ``elapsed_seconds``,
        ``video_anomaly_kind`` and ``error`` with its own view of the round.
        """
        diagnostics = (
            inference_result.diagnostics.model_copy(deep=True)
            if inference_result is not None and inference_result.diagnostics is not None
            else SampleAndInferDiagnostics()
        )

        if clip_result is not None:
            diagnostics.temp_video_hash = clip_result.file_hash
            diagnostics.temp_video_bytes = clip_result.file_size
            diagnostics.temp_video_manifest = clip_result.manifest

        diagnostics.internal_frame_range = result.get("inferred_frame_range")
        diagnostics.elapsed_seconds = round(elapsed_seconds, 6)

        # Map agent-level errors onto the diagnostics error field.
        infra_error = result.get("infra_error")
        validation_error = result.get("validation_error")
        if infra_error is not None:
            diagnostics.error = ValidationErrorInfo(
                code=infra_error.get("code", "infra_failed"),
                message=infra_error.get("message", "基础设施故障"),
                field=None,
            )
        elif validation_error is not None:
            diagnostics.error = ValidationErrorInfo(**validation_error)

        # Video anomaly classification.
        model_output = result.get("model_output") or {}
        has_fracture = model_output.get("has_fracture")
        output_type = model_output.get("type")
        if has_fracture is None and output_type == FractureType.VIDEO_ABNORMAL:
            diagnostics.video_anomaly_kind = "fracture_presence_unknown"
        elif (
            has_fracture is True
            and output_type == FractureType.VIDEO_ABNORMAL
        ):
            diagnostics.video_anomaly_kind = "fracture_time_unknown"

        return diagnostics

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        """Run the iterative loop and return the final output dict."""
        messages = self._build_system_messages()
        self._emit(
            "video_started",
            video_path=self.video_meta.get("video_path"),
            duration_sec=self.video_meta.get("duration", 0.0),
            max_rounds=self.max_rounds,
            initial_candidate=list(self.candidate),
        )

        for round_idx in range(self.max_rounds):
            self._emit(
                "round_started",
                round=round_idx,
                display_round=round_idx + 1,
                state=self.state,
                candidate=list(self.candidate),
            )
            try:
                response = self.llm.chat_with_tools(
                    messages=messages,
                    tools=TOOLS_SCHEMA,
                    temperature=self.temperature,
                )
            except Exception as exc:
                logger.exception("Decision backend failed")
                return RunnerResult(
                    ok=False,
                    error=RunnerError(
                        stage="decision_backend",
                        code="decision_backend_error",
                        message=f"决策模型调用失败: {exc}",
                    ),
                ).model_dump()
            message = response.choices[0].message

            # The LLM must output tool_calls; plain text is not acceptable.
            if not getattr(message, "tool_calls", None):
                messages.append({"role": "assistant", "content": message.content or ""})
                messages.append(
                    {"role": "user", "content": "请使用 tool_calls 输出你的决策。"}
                )
                continue

            tool_call = message.tool_calls[0]
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            # --- Pydantic schema validation (Fix 7) ---
            try:
                if tool_name == "terminate":
                    tool_args = ToolTerminate(**tool_args).model_dump()
                elif tool_name == "sample_and_infer":
                    tool_args = ToolSampleAndInfer(**tool_args).model_dump()
            except ValidationError as ve:
                err_detail = {
                    "error": f"工具参数校验失败: {ve.errors()}",
                    "tool_name": tool_name,
                    "received_args": tool_args,
                }
                messages.append(
                    self._assistant_tool_message(message, tool_call, tool_name)
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(err_detail, ensure_ascii=False),
                    }
                )
                self._emit(
                    "llm_tool_call",
                    round=round_idx,
                    display_round=round_idx + 1,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    reasoning=message.content or "",
                    validation_error=str(ve.errors()),
                )
                continue

            self._emit(
                "llm_tool_call",
                round=round_idx,
                display_round=round_idx + 1,
                tool_name=tool_name,
                tool_args=tool_args,
                reasoning=message.content or "",
            )

            if tool_name == "terminate":
                allowed, reason = self._can_terminate(tool_args, round_idx)
                self._emit(
                    "termination_requested",
                    round=round_idx,
                    display_round=round_idx + 1,
                    allowed=allowed,
                    reason=reason,
                    tool_args=tool_args,
                )
                if allowed:
                    self.state = "TERMINATED"
                    final_args = self._build_final_args(tool_args)
                    result = self._finalize(final_args)
                    self._persist_summary(result)
                    self._emit("video_finished", result=result)
                    return result

                messages.append(self._assistant_tool_message(message, tool_call, tool_name))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            {"allowed": False, "reason": reason}, ensure_ascii=False
                        ),
                    }
                )
                continue

            if tool_name == "sample_and_infer":
                # Program-owned scheduling: after an initial global negative,
                # the decision model only supplies the prompt. The five
                # coverage ranges and mandatory same-range rechecks cannot be
                # overridden through tool arguments.
                if self.pending_recheck_range is not None:
                    tool_args["sample_range"] = list(self.pending_recheck_range)
                elif self.state == "INITIAL":
                    # The first semantic inspection is program-owned and must
                    # cover the complete video. Invalid retries remain in
                    # INITIAL and are forced to the same full range.
                    tool_args["sample_range"] = [
                        0.0,
                        float(self.video_meta.get("duration", 0.0)),
                    ]
                elif self.state == "COVERAGE" and self.coverage_index < 5:
                    tool_args["sample_range"] = self._coverage_ranges()[self.coverage_index]
                sample_range = list(tool_args["sample_range"])
                self._emit(
                    "sample_and_infer_started",
                    round=round_idx,
                    display_round=round_idx + 1,
                    sample_range=sample_range,
                )

                internal_result = self._execute_sample_and_infer(tool_args, round_idx)
                self._emit(
                    "sample_and_infer_finished",
                    round=round_idx,
                    display_round=round_idx + 1,
                    model_output=self._to_json_value(internal_result.get("model_output")),
                    inferred_time_range=internal_result.get("inferred_time_range"),
                    inferred_frame_range=internal_result.get("inferred_frame_range"),
                    validation_error=internal_result.get("validation_error"),
                    round_confidence_level=internal_result.get("round_confidence_level"),
                )

                previous_state = self.state
                previous_candidate = list(self.candidate)
                self._transition(internal_result, round_idx)
                self._emit(
                    "state_updated",
                    round=round_idx,
                    display_round=round_idx + 1,
                    previous_state=previous_state,
                    state=self.state,
                    previous_candidate=previous_candidate,
                    candidate=list(self.candidate),
                )
                self._log_round(round_idx, message, internal_result)

                # Sampling and inference transport failures have already
                # exhausted their component retry budget. Continuing the
                # semantic state machine would turn an infrastructure failure
                # into a misleading domain result.
                infra_error = internal_result.get("infra_error")
                if infra_error is not None:
                    result = RunnerResult(
                        ok=False,
                        error=RunnerError(**infra_error),
                    ).model_dump()
                    self._persist_summary(result)
                    self._emit("video_finished", result=result)
                    return result

                # Build compact result for LLM tool response.
                compact = self._build_compact_result(internal_result)
                messages.append(self._assistant_tool_message(message, tool_call, tool_name))
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(
                            self._to_json_value(compact), ensure_ascii=False
                        ),
                    }
                )

                if self.state == "TERMINATED":
                    result = self._force_terminate()
                    self._persist_summary(result)
                    self._emit("video_finished", result=result)
                    return result

                messages.append({
                    "role": "user",
                    "content": build_meta_agent_user_context(
                        video_meta=self.video_meta,
                        config=self.config,
                        current_round=min(round_idx + 2, self.max_rounds),
                        candidate=self.candidate,
                        history=self.history,
                    ),
                })
                continue

            # Unknown tool: report and let the LLM retry.
            messages.append(self._assistant_tool_message(message, tool_call, tool_name))
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(
                        {"error": f"未知工具: {tool_name}"}, ensure_ascii=False
                    ),
                }
            )

        result = self._force_terminate()
        self._persist_summary(result)
        self._emit("video_finished", result=result)
        return result

    # ------------------------------------------------------------------
    # Message builders
    # ------------------------------------------------------------------
    def _build_system_messages(self) -> list[dict[str, Any]]:
        """Return the initial message list with system + first user context."""
        return [
            {"role": "system", "content": META_AGENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_meta_agent_user_context(
                    video_meta=self.video_meta,
                    config=self.config,
                    current_round=1,
                    candidate=self.candidate,
                    history=self.history,
                ),
            },
        ]

    def _assistant_tool_message(
        self,
        message: Any,
        tool_call: Any,
        tool_name: str,
    ) -> dict[str, Any]:
        """Format an assistant message that includes a tool_call."""
        return {
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": tool_call.function.arguments,
                    },
                }
            ],
        }

    # ------------------------------------------------------------------
    # Compact result builder (for LLM tool response)
    # ------------------------------------------------------------------
    @staticmethod
    def _build_compact_result(internal: dict[str, Any]) -> SampleAndInferResult:
        """Build a ``SampleAndInferResult`` from the internal result dict.

        Only the six contract fields are exposed to the decision model.
        Infrastructure errors carry ``infra_error`` instead of
        ``validation_error``; map them to a validation_error for the
        LLM-facing envelope so the decision model can see the failure.
        """
        validation_error = internal.get("validation_error")
        infra_error = internal.get("infra_error")
        if validation_error is None and infra_error is not None:
            validation_error = {
                "code": infra_error.get("code", "infra_failed"),
                "message": infra_error.get("message", "基础设施故障"),
                "field": None,
            }
        return SampleAndInferResult(
            ok=bool(internal.get("ok")),
            sample_range=internal.get("sample_range", [0.0, 0.0]),
            model_output=internal.get("model_output"),
            inferred_time_range=internal.get("inferred_time_range"),
            validation_error=(
                ValidationErrorInfo(**validation_error)
                if isinstance(validation_error, dict)
                else None
            ),
            attempts=int(internal.get("attempts", 1)),
        )

    # ------------------------------------------------------------------
    # Termination rules
    # ------------------------------------------------------------------
    def _can_terminate(self, args: dict[str, Any], round_idx: int) -> tuple[bool, str]:
        """Determine whether the current state allows termination.

        Uses ``ToolTerminate`` schema fields: ``status``, ``evidence_rounds``,
        ``unrecognized_reason``.
        """
        status = args.get("status")

        # -- unrecognized: model explicitly reports it cannot form a conclusion --
        if status == "unrecognized":
            unrecognized_reason = args.get("unrecognized_reason")
            valid_reasons = {
                "video_anomaly", "not_clamped", "conflicting_results",
                "invalid_model_output", "insufficient_confidence",
                "incomplete_coverage", "max_rounds",
            }
            if unrecognized_reason not in valid_reasons:
                return False, (
                    f"unrecognized_reason 无效: {unrecognized_reason}，"
                    f"须为 {sorted(valid_reasons)}"
                )
            if unrecognized_reason in {"video_anomaly", "not_clamped"}:
                if not self._has_consistent_special_recheck(unrecognized_reason):
                    return False, "视频异常或未夹紧必须在同一区间得到两次一致结果"
            return True, "模型明确报告无法识别"

        if status == "no_fracture":
            if self._has_complete_no_fracture_coverage():
                return True, "五个固定重叠区间均得到高于门槛的未断裂结果"
            return False, "尚未完成五个固定重叠区间的未断裂覆盖检查"

        # -- fracture: check evidence threshold and convergence --
        if status == "fracture":
            evidence_rounds: list[int] = args.get("evidence_rounds") or []
            # evidence_rounds are stable 0-based history evidence_index values
            # explicitly shown to the decision model, not Agent loop rounds.
            unique_rounds = list(set(r for r in evidence_rounds if r >= 0))
            if len(unique_rounds) < 2:
                return False, (
                    f"去重后 evidence_rounds 不足 2 个独立轮次 "
                    f"(原始: {evidence_rounds}, 去重: {unique_rounds})"
                )

            positive_evidence = [
                r for r in unique_rounds
                if r < len(self.history) and self._round_is_local_fracture(self.history[r])
            ]
            if len(positive_evidence) < 2:
                return False, (
                    f"需要至少 2 轮断裂证据支撑，当前 evidence_rounds 中仅有 "
                    f"{len(positive_evidence)} 轮有效断裂记录"
                )

            # --- Fix 3a: intersection check across all positive evidence ---
            evidence_ranges: list[list[float]] = []
            for r_idx in positive_evidence:
                rng = self.history[r_idx]["result"].get("inferred_time_range")
                if rng and len(rng) == 2:
                    evidence_ranges.append(rng)
            if len(evidence_ranges) >= 2:
                inter_start = max(r[0] for r in evidence_ranges)
                inter_end = min(r[1] for r in evidence_ranges)
                if inter_start >= inter_end:
                    return False, (
                        f"正证据轮次 {positive_evidence} 的 inferred_time_range "
                        f"无交集，无法收敛，请继续验证"
                    )
                all_strictly_local = all(
                    self._sample_range_is_local(self.history[r].get("result", {}).get("sample_range"))
                    for r in positive_evidence
                )
                if all_strictly_local and inter_end - inter_start > 1.0 + 1e-9:
                    return False, (
                        f"局部证据共同交集宽度 {inter_end - inter_start:.2f}s "
                        "超过公共结果 1 秒上限，请继续局部复查"
                    )

            # Must converge or exhaust rounds.
            if self.candidate[1] - self.candidate[0] <= self.tolerance:
                if self.last_round_confidence_level == "不可信":
                    return False, "区间虽收敛但最新一轮置信度不可信，请继续验证"
                return True, "候选区间宽度 ≤ tolerance"
            # --- Fix 3d: max_rounds requires strict tolerance (no 2× relaxation) ---
            if round_idx >= self.max_rounds - 1:
                width = self.candidate[1] - self.candidate[0]
                if width <= self.tolerance:
                    return True, "达到 max_rounds 且候选区间宽度 ≤ tolerance"
                return False, (
                    f"达到 max_rounds 但候选区间宽度 {width:.2f}s 超过 "
                    f"tolerance ({self.tolerance:.2f}s)，无法终止"
                )

            return False, "区间尚未收敛，请继续调用 sample_and_infer"

        return False, f"未知 status: {status}"

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------
    def _transition(self, result: dict[str, Any], round_idx: int) -> None:
        """Update state, candidate interval and counters from a tool result."""
        infra_error = result.get("infra_error")
        if infra_error:
            # Infrastructure failures must not drive state transitions, fracture
            # counting, or candidate updates.
            self.infra_fail_count += 1
            if self.infra_fail_count >= 2:
                self.state = "TERMINATED"
                self.infra_terminated = True
            return

        # Reset infra failure counter on any non-infra round.
        self.infra_fail_count = 0

        validation_error = result.get("validation_error")
        if validation_error:
            # Validation failures must not drive state transitions.  Record low
            # confidence and optionally fall back to avoid getting stuck.
            self.last_round_confidence_level = "不可信"
            self.low_conf_count += 1
            if self.low_conf_count >= self.max_low_conf_rounds:
                self.candidate = self._expand_candidate(self.candidate)
                self.low_conf_count = 0
                result["fallback"] = "validation_error_expanded_to_parent_range"
            return

        model_output = result.get("model_output", {})
        has_fracture = model_output.get("has_fracture", False)
        new_range = result.get("inferred_time_range")
        confidence_level = result.get("round_confidence_level", "不可信")

        # Both legal VIDEO_ABNORMAL combinations carry no usable temporal
        # evidence.  Even when fracture presence is confirmed, the round must
        # never enter narrowing or count as fracture evidence.
        if model_output.get("type") == FractureType.VIDEO_ABNORMAL:
            self.last_round_confidence_level = confidence_level
            self._update_special_recheck(result)
            return

        # ------------------------------------------------------------------
        # has_fracture is None: video anomaly / cannot determine
        # Do not enter NO_FRACTURE state, do not increment counters.
        # ------------------------------------------------------------------
        if has_fracture is None:
            self.last_round_confidence_level = confidence_level
            self._update_special_recheck(result)
            return

        # ------------------------------------------------------------------
        # No-fracture path (has_fracture is False)
        # ------------------------------------------------------------------
        if has_fracture is False:
            self.last_round_confidence_level = confidence_level

            if model_output.get("type") == FractureType.NOT_CLAMPED:
                self._update_special_recheck(result)
                return

            if self.state == "COVERAGE":
                expected = self._coverage_ranges()[self.coverage_index]
                confidence = float(model_output.get("confidence", 0.0))
                if (
                    self._same_range(result.get("sample_range"), expected)
                    and model_output.get("type") == FractureType.NO_FRACTURE
                    and confidence >= self.confidence_threshold
                ):
                    self.coverage_index += 1
                    self.no_fracture_count = self.coverage_index
                    if self.coverage_index >= 5:
                        self.state = "NO_FRACTURE"
                return

            is_global_scope = (
                self.state == "INITIAL"
                or (
                    self.candidate[0] <= 0.0
                    and self.candidate[1] >= self.video_meta.get("duration", 0.0)
                )
            )

            if is_global_scope:
                self.state = "COVERAGE"
                self.coverage_index = 0
                self.no_fracture_count = 0
                return

            # Focused sub-interval returned false: expand and fall back.
            self.focus_miss_count += 1
            self.candidate = self._expand_candidate(self.candidate)
            result["fallback"] = "focus_false_expanded_to_parent_range"
            return

        # ------------------------------------------------------------------
        # Fracture path
        # ------------------------------------------------------------------
        self.no_fracture_count = 0
        self.pending_recheck_range = None
        if self.state in ("INITIAL", "NO_FRACTURE", "COVERAGE"):
            self.state = "NARROWING"

        # Normal interval update and conflict handling.
        if new_range:
            c0, c1 = self.candidate
            n0, n1 = new_range

            if c0 <= n0 and n1 <= c1:
                self.candidate = new_range
                self.conflict_count = 0
                self.low_conf_count = 0
                self.focus_miss_count = 0
            elif not (n1 < c0 or n0 > c1):
                self.candidate = [max(c0, n0), min(c1, n1)]
                self.conflict_count = 0
                self.low_conf_count = 0
                self.focus_miss_count = 0
            else:
                confidence = model_output.get("confidence", 0.5)
                if self._is_low_confidence(confidence):
                    self.low_conf_count += 1
                    result["conflict_handled"] = "discarded_low_confidence"
                else:
                    self.candidate = [min(c0, n0), max(c1, n1)]
                    self.conflict_count += 1
                    result["conflict_handled"] = "expanded_candidate"

                if self.low_conf_count >= self.max_low_conf_rounds:
                    self.candidate = self._expand_candidate(self.candidate)
                    self.low_conf_count = 0
                    result["fallback"] = "expanded_to_parent_range"

        # Enter verification when the interval is narrow enough.
        if self.state == "NARROWING" and (self.candidate[1] - self.candidate[0]) <= self.tolerance:
            self.state = "VERIFYING"

        # Irreconcilable conflicts force termination.
        if self.conflict_count >= 3:
            self.state = "TERMINATED"

        self.last_round_confidence_level = confidence_level

    def _expand_candidate(self, candidate: list[float]) -> list[float]:
        """Expand candidate interval by 1.5x around its center, clamped to [0, duration]."""
        width = candidate[1] - candidate[0]
        center = (candidate[0] + candidate[1]) / 2
        half = width * 0.75
        duration = self.video_meta.get("duration", 0.0)
        return [
            max(0.0, center - half),
            min(duration, center + half),
        ]

    # ------------------------------------------------------------------
    # Forced / final termination
    # ------------------------------------------------------------------
    def _round_has_fracture(self, entry: dict[str, Any]) -> bool:
        """Safely check whether a history entry has a positive fracture prediction."""
        result = entry.get("result", {})
        model_output = result.get("model_output")
        inferred_range = result.get("inferred_time_range")
        return (
            isinstance(model_output, dict)
            and model_output.get("has_fracture", False) is True
            and model_output.get("type") in FRACTURE_CLASSES
            and isinstance(inferred_range, list)
            and len(inferred_range) == 2
        )

    def _round_is_local_fracture(self, entry: dict[str, Any]) -> bool:
        """Require fracture evidence to come from a genuine local inspection."""
        if not self._round_has_fracture(entry):
            return False
        result = entry.get("result", {})
        sample_range = result.get("sample_range")
        inferred_range = result.get("inferred_time_range")
        return (
            self._sample_range_is_local(sample_range)
            and isinstance(inferred_range, list)
            and len(inferred_range) == 2
            and sample_range[0] <= inferred_range[0] < inferred_range[1] <= sample_range[1]
        )

    def _sample_range_is_local(self, sample_range: Any) -> bool:
        duration = float(self.video_meta.get("duration", 0.0))
        return (
            isinstance(sample_range, list)
            and len(sample_range) == 2
            and sample_range[1] - sample_range[0] < duration - 1e-9
        )

    def _coverage_ranges(self) -> list[list[float]]:
        """Return the five fixed D/4 windows required after a global negative."""
        duration = float(self.video_meta.get("duration", 0.0))
        return [
            [duration * start / 16.0, duration * (start + 4) / 16.0]
            for start in (0, 3, 6, 9, 12)
        ]

    @staticmethod
    def _same_range(left: Any, right: Any, epsilon: float = 1e-6) -> bool:
        return (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right) == 2
            and abs(float(left[0]) - float(right[0])) <= epsilon
            and abs(float(left[1]) - float(right[1])) <= epsilon
        )

    def _has_complete_no_fracture_coverage(self) -> bool:
        """Validate five fixed windows from recorded, legal model results."""
        for expected in self._coverage_ranges():
            matched = False
            for entry in self.history:
                result = entry.get("result", {})
                output = result.get("model_output") or {}
                if (
                    result.get("ok") is True
                    and self._same_range(result.get("sample_range"), expected)
                    and output.get("has_fracture") is False
                    and output.get("type") == FractureType.NO_FRACTURE
                    and float(output.get("confidence", 0.0)) >= self.confidence_threshold
                ):
                    matched = True
                    break
            if not matched:
                return False
        return True

    def _has_consistent_special_recheck(self, reason: str) -> bool:
        """Require two matching anomaly/not-clamped results on the same range."""
        matches: list[tuple[list[float], tuple[Any, Any]]] = []
        for entry in self.history:
            result = entry.get("result", {})
            output = result.get("model_output") or {}
            is_match = (
                reason == "video_anomaly" and output.get("type") == FractureType.VIDEO_ABNORMAL
            ) or (
                reason == "not_clamped" and output.get("type") == FractureType.NOT_CLAMPED
            )
            if result.get("ok") is True and is_match:
                matches.append(
                    (result.get("sample_range"), (output.get("has_fracture"), output.get("type")))
                )
        for index, (sample_range, signature) in enumerate(matches):
            if any(
                self._same_range(sample_range, other_range) and signature == other_signature
                for other_range, other_signature in matches[index + 1 :]
            ):
                return True
        return False

    def _update_special_recheck(self, result: dict[str, Any]) -> None:
        """Schedule or complete the mandatory same-range special-result recheck."""
        sample_range = result.get("sample_range")
        if not isinstance(sample_range, list) or len(sample_range) != 2:
            return
        if self.pending_recheck_range is None:
            self.pending_recheck_range = list(sample_range)
            return
        if self._same_range(sample_range, self.pending_recheck_range):
            self.pending_recheck_range = None

    def _build_final_args(self, tool_args: dict[str, Any]) -> dict[str, Any]:
        """Build the final result args from code-layer aggregation.

        Uses the LLM's ``terminate`` proposal as a guide but derives
        ``time_range`` and validates types against multi-round evidence.
        """
        status = tool_args.get("status")

        if status == "unrecognized":
            return {
                "status": "unrecognized",
                "time_range": None,
                "fracture_type": None,
                "location": None,
                "confidence": None,
                "unrecognized_reason": tool_args.get("unrecognized_reason", "max_rounds"),
            }

        if status == "no_fracture":
            return self._build_non_fracture_args(tool_args)

        if status == "fracture":
            # Use the same 0-based history evidence_index semantics as
            # _can_terminate and the decision-model context.
            evidence_rounds: list[int] = tool_args.get("evidence_rounds") or []
            if evidence_rounds:
                positive_rounds = [
                    self.history[r] for r in evidence_rounds
                    if r < len(self.history) and self._round_has_fracture(self.history[r])
                ]
            else:
                # Force-terminate path: no evidence_rounds provided, use all history.
                positive_rounds = [r for r in self.history if self._round_has_fracture(r)]
            if positive_rounds:
                return self._build_fracture_args(positive_rounds, tool_args)
            # No positive evidence – downgrade.
            return self._build_non_fracture_args({
                "status": "no_fracture",
                "confidence": tool_args.get("confidence", 0.5),
                "downgrade_reason": "no_positive_evidence_for_fracture_status",
            })

        # Unknown status – fall back to no_fracture.
        logger.warning("Unknown terminate status %s; falling back to no_fracture", status)
        return self._build_non_fracture_args({
            "status": "no_fracture",
            "confidence": 0.0,
            "downgrade_reason": f"unknown_terminate_status_{status}",
        })

    def _build_fracture_args(
        self,
        positive_rounds: list[dict[str, Any]],
        tool_args: dict[str, Any],
    ) -> dict[str, Any]:
        """Aggregate a final fracture result from the best positive round."""
        best_round = self._select_best_round(positive_rounds)
        best_result = best_round["result"]
        best_model_output = best_result.get("model_output", {})
        best_frames = best_result.get("manifest") or best_result.get("frames", [])

        # --- Fix 3b: use intersection of all positive evidence time ranges ---
        all_ranges: list[list[float]] = []
        for r in positive_rounds:
            rng = r["result"].get("inferred_time_range")
            if rng and len(rng) == 2:
                all_ranges.append(rng)

        if len(all_ranges) >= 2:
            inter_start = max(r[0] for r in all_ranges)
            inter_end = min(r[1] for r in all_ranges)
            if inter_start < inter_end:
                best_time_range: list[float] | None = [inter_start, inter_end]
            else:
                # No intersection — fall back to best single round.
                logger.warning(
                    "Positive evidence time ranges have no intersection; "
                    "falling back to best single round."
                )
                best_time_range = best_result.get("inferred_time_range")
        else:
            best_time_range = best_result.get("inferred_time_range")

        if best_time_range is None:
            logger.warning(
                "Best positive round lacks inferred_time_range; "
                "falling back to candidate %s",
                self.candidate,
            )
            best_time_range = list(self.candidate)

        # Frame range: inferred from best round.
        best_frame_range = best_result.get("inferred_frame_range")
        if best_frame_range is None and best_time_range is not None and len(best_frames) >= 2:
            best_frame_range = self._time_range_to_frame_range(best_frames, best_time_range)

        voted_type = self._vote_field(
            [r["result"]["model_output"].get("type") for r in positive_rounds],
            valid_set=FRACTURE_CLASSES,
        )
        if voted_type is None:
            fallback_type = tool_args.get("fracture_type")
            if fallback_type in FRACTURE_CLASSES:
                voted_type = fallback_type
            else:
                fallback_type = best_model_output.get("type")
                if fallback_type in FRACTURE_CLASSES:
                    voted_type = fallback_type
                else:
                    reason = "all_fracture_types_invalid"
                    logger.warning(
                        "All positive round types and LLM fracture_type are invalid; "
                        "downgrading to no-fracture (%s)",
                        reason,
                    )
                    return self._build_non_fracture_args({
                        "status": "no_fracture",
                        "confidence": 0.0,
                        "downgrade_reason": reason,
                    })

        voted_location = self._vote_field(
            [r["result"]["model_output"].get("location") for r in positive_rounds],
            valid_set={LocationType.INSIDE, LocationType.OUTSIDE},
        )
        if voted_location is None:
            fallback_location = tool_args.get("location")
            if fallback_location in {LocationType.INSIDE, LocationType.OUTSIDE}:
                voted_location = fallback_location
            else:
                fallback_location = best_model_output.get("location")
                if fallback_location in {LocationType.INSIDE, LocationType.OUTSIDE}:
                    voted_location = fallback_location
                else:
                    voted_location = "unknown"

        final_confidence = self._aggregate_confidence(positive_rounds)
        return {
            "status": "fracture",
            "time_range": best_time_range,
            "fracture_type": voted_type,
            "location": voted_location,
            "confidence": final_confidence,
            "unrecognized_reason": None,
            # Internal metadata for frame_range fallback in _finalize
            "_frame_range": best_frame_range,
        }

    def _build_non_fracture_args(self, tool_args: dict[str, Any]) -> dict[str, Any]:
        """Normalize a no-fracture termination result.

        No-fracture class is constrained to valid non-fracture labels;
        ``location``, ``time_range`` and ``fracture_type`` are forced to
        ``None``.
        """
        args: dict[str, Any] = {
            "status": "no_fracture",
            "time_range": None,
            "fracture_type": None,
            "location": None,
            "confidence": tool_args.get("confidence", 0.5),
            "unrecognized_reason": None,
        }
        if "downgrade_reason" in tool_args:
            args["downgrade_reason"] = tool_args["downgrade_reason"]
        return args

    def _force_terminate(self) -> dict[str, Any]:
        """Construct a final output when rounds are exhausted or conflicts unresolvable."""
        # Fix 3a: consecutive infrastructure failures → RunnerResult(ok=false).
        if self.infra_terminated:
            return RunnerResult(
                ok=False,
                error=RunnerError(
                    stage="internal",
                    code="consecutive_infra_failures",
                    message=(
                        f"连续 {self.infra_fail_count} 轮基础设施失败，"
                        f"无法完成分析"
                    ),
                ),
            ).model_dump()

        positive_rounds = [r for r in self.history if self._round_has_fracture(r)]
        if self.state == "NO_FRACTURE":
            if positive_rounds:
                logger.info(
                    "NO_FRACTURE state machine priority takes precedence over "
                    "%d stale positive round(s)",
                    len(positive_rounds),
                )
            return self._finalize(self._build_non_fracture_args({
                "status": "no_fracture",
                "confidence": 0.0,
            }))

        # Exhaustion cannot manufacture a fracture from insufficient or wide
        # evidence.  Only the normal terminate path may approve a fracture.
        return self._finalize({
            "status": "unrecognized",
            "time_range": None,
            "fracture_type": None,
            "location": None,
            "confidence": None,
            "unrecognized_reason": "max_rounds",
            "downgrade_reason": (
                "rounds exhausted before fracture/no-fracture evidence "
                "satisfied the contract"
            ),
        })

    def _finalize(self, args: dict[str, Any]) -> dict[str, Any]:
        """Return the final output dict including metadata and history.

        Validates the public fields against ``FinalOutput``; extra metadata
        (``rounds``, ``history``, ``downgrade_reason``, ``frame_range``) is
        appended after validation.
        """
        status = args.get("status", "no_fracture")
        output: dict[str, Any] = {
            "video_id": self.video_meta.get("video_id", "unknown"),
            "status": status,
            "time_range": args.get("time_range") if status == "fracture" else None,
            "fracture_type": args.get("fracture_type") if status == "fracture" else None,
            "location": args.get("location") if status == "fracture" else None,
            "confidence": args.get("confidence"),
            "unrecognized_reason": args.get("unrecognized_reason"),
        }
        # Validate against the contract schema; on failure, downgrade to unrecognized.
        try:
            FinalOutput(**output)
        except Exception as exc:
            reason = f"Final output schema validation failed: {exc}"
            logger.warning(reason)
            output["status"] = "unrecognized"
            output["time_range"] = None
            output["fracture_type"] = None
            output["location"] = None
            output["confidence"] = None
            output["unrecognized_reason"] = "invalid_model_output"
            output["downgrade_reason"] = reason

        # Append metadata.
        output["rounds"] = len(self.history)
        output["history"] = self.history
        downgrade_reason = args.get("downgrade_reason")
        if downgrade_reason is not None:
            output["downgrade_reason"] = downgrade_reason

        # Carry through frame_range for downstream consumers that still need it.
        frame_range = args.get("_frame_range")
        if frame_range is not None:
            output["frame_range"] = frame_range

        return output

    # ------------------------------------------------------------------
    # Aggregation helpers
    # ------------------------------------------------------------------
    def _select_best_round(self, positive_rounds: list[dict[str, Any]]) -> dict[str, Any]:
        """Select the best positive round by confidence level and interval width."""
        level_score = {"高": 3, "中": 2, "低": 1, "不可信": 0}

        def score(r: dict[str, Any]) -> tuple[int, float]:
            result = r.get("result", {})
            level = result.get("round_confidence_level", "不可信")
            rng = result.get("inferred_time_range")
            width = rng[1] - rng[0] if rng else float("inf")
            return (level_score.get(level, 0), -width)

        return max(positive_rounds, key=score)

    def _vote_field(self, values: list[Any], valid_set: set[str]) -> str | None:
        """Majority vote among valid values."""
        from collections import Counter

        filtered = [v for v in values if v in valid_set]
        if not filtered:
            return None
        return Counter(filtered).most_common(1)[0][0]

    def _time_range_to_frame_range(
        self, frames: list[dict[str, Any]], time_range: list[float]
    ) -> list[int] | None:
        """Recover original frame indices from timestamps in the manifest/frames."""
        start_frame = next(
            (f["original_frame"] for f in frames if abs(f["timestamp"] - time_range[0]) < 1e-6),
            None,
        )
        end_frame = next(
            (f["original_frame"] for f in frames if abs(f["timestamp"] - time_range[1]) < 1e-6),
            None,
        )
        if start_frame is not None and end_frame is not None:
            return [start_frame, end_frame]
        return None

    def _aggregate_confidence(self, positive_rounds: list[dict[str, Any]]) -> float:
        """Average model confidence across positive rounds."""
        if not positive_rounds:
            return 0.0
        values = [
            r["result"]["model_output"].get("confidence", 0.0)
            for r in positive_rounds
        ]
        return round(sum(values) / len(values), 4)

    def _is_low_confidence(self, confidence: float) -> bool:
        """Return whether ``confidence`` is below the configured threshold."""
        return confidence < self.confidence_threshold

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------
    def _execute_sample_and_infer(
        self, args: dict[str, Any], round_idx: int
    ) -> dict[str, Any]:
        """Run one round of sample + infer and return the internal result.

        Builds a continuous clip via ``build_with_manifest``, sends it to the
        inference model, decodes the ``ModelOutput``, and maps
        ``fracture_between`` back to original video time/frame ranges using
        the clip manifest.  Also builds, persists and attaches
        ``SampleAndInferDiagnostics`` to the returned dict.
        """
        round_start = time.perf_counter()
        sample_range = list(args["sample_range"])
        clip_result: ClipBuildResult | None = None
        inference_result: InferenceResult | None = None

        def _finalize(result: dict[str, Any]) -> dict[str, Any]:
            elapsed = time.perf_counter() - round_start
            diagnostics = self._build_round_diagnostics(
                result=result,
                clip_result=clip_result,
                inference_result=inference_result,
                elapsed_seconds=elapsed,
            )
            self._persist_diagnostics(round_idx, diagnostics)
            result["diagnostics"] = diagnostics.model_dump(mode="json", exclude_none=True)
            return result

        # Runtime sample_range validity against video boundaries.
        video_duration = self.video_meta.get("duration", 0.0)
        start, end = sample_range
        if not (0 <= start < end <= video_duration):
            return _finalize(
                self._error_result(
                    sample_range=sample_range,
                    code="invalid_sample_range",
                    message=(
                        f"sample_range [{start}, {end}] 超出合法区间 "
                        f"[0, {video_duration}] 或不是严格递增"
                    ),
                    field="sample_range",
                )
            )

        prompt = args.get("prompt") or build_sample_and_infer_prompt(
            sample_range=sample_range,
            config=self.config,
            previous_context=f"当前候选区间为 {self.candidate}",
        )

        # Runtime length re-check against configurable limit (default 4096).
        agent_cfg = self.config.get("agent", {})
        max_len = agent_cfg.get("max_prompt_length", 4096)
        if len(prompt) > max_len:
            return _finalize(
                self._error_result(
                    sample_range=sample_range,
                    code="prompt_too_long",
                    message=(
                        f"prompt length {len(prompt)} exceeds configured "
                        f"max_prompt_length {max_len}"
                    ),
                    field="prompt",
                )
            )

        source_video = self.video_meta["video_path"]

        # Build continuous clip + manifest.
        try:
            clip_result: ClipBuildResult = self.clip_builder.build_with_manifest(
                source_video=source_video,
                sample_range=sample_range,
            )
        except Exception as exc:
            logger.warning("Clip build failed: %s", exc)
            return _finalize(
                self._infra_error_result(
                    sample_range,
                    stage="sampling",
                    code="sampling_error",
                    message=f"无法构建临时视频片段: {exc}",
                )
            )

        manifest = clip_result.manifest

        # Run inference.
        try:
            inference_result = self.inference_client.infer(clip_result, prompt)
        except Exception as exc:
            logger.warning("Inference transport/execution failed: %s", exc)
            return _finalize(
                self._infra_error_result(
                    sample_range,
                    stage="inference_transport",
                    code="inference_transport",
                    message=f"推理请求失败: {exc}",
                )
            )

        # Build internal result base.
        result: dict[str, Any] = {
            "ok": inference_result.ok,
            "sample_range": sample_range,
            "model_output": inference_result.model_output,
            "inferred_time_range": None,
            "inferred_frame_range": None,
            "validation_error": None,
            "attempts": inference_result.attempts,
            "manifest": manifest,
            "model_video_path": clip_result.path,
            "round_confidence_level": "不可信",
        }

        # Handle inference failure.
        if not inference_result.ok:
            result["ok"] = False
            result["model_output"] = None
            err = inference_result.error
            result["validation_error"] = {
                "code": err.code if err else "inference_failed",
                "message": err.message if err else "模型输出解析失败",
                "field": err.field if err else None,
            }
            return _finalize(result)

        # Server-side preprocessing metadata is mandatory for every semantic
        # result. Negative/anomaly predictions are not exempt: accepting them
        # without proving which frames the model saw would make coverage and
        # repeat-check evidence unverifiable.
        preprocessing = inference_result.preprocessing
        pp_error_code = _validate_preprocessing_meta(preprocessing)
        if pp_error_code is not None:
            return _finalize(
                self._infra_error_result(
                    sample_range,
                    stage="inference_transport",
                    code="missing_or_invalid_preprocessing_metadata",
                    message=f"服务端 preprocessing 元数据无效: {pp_error_code}",
                )
            )
        server_frames: list[dict[str, Any]] = preprocessing["frames"]

        # Derive confidence level.
        model_output = result["model_output"] or {}
        confidence = model_output.get("confidence", 0.5)
        result["round_confidence_level"] = _confidence_to_level(confidence)

        has_fracture = (
            model_output.get("has_fracture") is True
            and model_output.get("fracture_between") is not None
        )

        # ------------------------------------------------------------------
        # Case 1: Preprocessing present and valid — use server frames.
        # ------------------------------------------------------------------
        if has_fracture:
            fracture_between = model_output["fracture_between"]
            n = len(server_frames)  # Server-reported frame count

            def _reject_indices(msg: str) -> dict[str, Any]:
                result["ok"] = False
                result["model_output"] = None
                result["inferred_time_range"] = None
                result["validation_error"] = {
                    "code": "invalid_index",
                    "message": msg,
                    "field": "fracture_between",
                }
                return _finalize(result)

            if len(fracture_between) != 2:
                return _finalize(
                    _reject_indices(
                        f"fracture_between 长度必须为 2，got {fracture_between}"
                    )
                )
            i, j = fracture_between
            if not (0 <= i < n and 0 <= j < n):
                return _finalize(
                    _reject_indices(
                        f"fracture_between {fracture_between} "
                        f"超出采样帧索引范围 [0, {n - 1}]"
                    )
                )
            if i == j:
                return _finalize(
                    _reject_indices(
                        f"fracture_between {fracture_between} "
                        f"必须是严格相邻的两帧 [i, i+1]"
                    )
                )

            # Map through server frames (authoritative frame table).
            # Map temporary-clip timestamps through the actual-PTS manifest.
            def _lookup_manifest(ts: float) -> dict[str, Any] | None:
                for entry in manifest:
                    clip_timestamp = entry.get("clip_timestamp", entry["timestamp"])
                    if abs(clip_timestamp - ts) < 0.0001:
                        return entry
                return None

            mapped_i = _lookup_manifest(server_frames[i]["timestamp"])
            mapped_j = _lookup_manifest(server_frames[j]["timestamp"])
            if mapped_i is not None and mapped_j is not None:
                result["inferred_time_range"] = [mapped_i["timestamp"], mapped_j["timestamp"]]
                result["inferred_frame_range"] = [
                    mapped_i["original_frame"], mapped_j["original_frame"]
                ]
                return _finalize(result)

            return _finalize(
                self._infra_error_result(
                    sample_range,
                    stage="inference_transport",
                    code="preprocessing_timestamp_mismatch",
                    message=(
                        "服务端采样时间戳无法与临时视频的实际帧清单对应，"
                        "拒绝使用本地推测映射"
                    ),
                )
            )

        return _finalize(result)

    def _error_result(
        self,
        sample_range: list[float],
        code: str,
        message: str,
        field: str | None = None,
        attempts: int = 1,
    ) -> dict[str, Any]:
        """Build an error internal result."""
        return {
            "ok": False,
            "sample_range": sample_range,
            "model_output": None,
            "inferred_time_range": None,
            "inferred_frame_range": None,
            "validation_error": {"code": code, "message": message, "field": field},
            "attempts": attempts,
            "manifest": [],
            "model_video_path": None,
            "round_confidence_level": "不可信",
        }

    def _infra_error_result(
        self,
        sample_range: list[float],
        stage: str,
        code: str,
        message: str,
    ) -> dict[str, Any]:
        """Build an infrastructure error internal result.

        Infrastructure failures (sampling, inference transport) are NOT
        validation errors.  They carry ``infra_error`` so that
        ``_transition`` can distinguish them from model-level failures.
        """
        return {
            "ok": False,
            "sample_range": sample_range,
            "model_output": None,
            "inferred_time_range": None,
            "inferred_frame_range": None,
            "infra_error": {"stage": stage, "code": code, "message": message},
            "validation_error": None,
            "attempts": 1,
            "manifest": [],
            "model_video_path": None,
            "round_confidence_level": "不可信",
        }

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    def _log_round(
        self,
        round_idx: int,
        message: Any,
        result: dict[str, Any] | None = None,
    ) -> None:
        """Record one round for final output and debugging."""
        log_entry: dict[str, Any] = {
            "round": round_idx,
            "model": self.llm.model_name,
            "reasoning": message.content or "",
            "tool_calls": [
                {
                    "name": tc.function.name,
                    "arguments": json.loads(tc.function.arguments),
                }
                for tc in (message.tool_calls or [])
            ],
        }
        if result is not None:
            log_entry["result"] = result
        self.history.append(log_entry)
        logger.info("Round %d: %s", round_idx, json.dumps(log_entry, ensure_ascii=False))

    # ------------------------------------------------------------------
    # Default inference client
    # ------------------------------------------------------------------
    def _default_inference_client(self) -> InferenceClient:
        """Create a default inference client from config or environment."""
        if os.getenv("INFERENCE_MOCK") == "1":
            return MockInferenceClient({
                "has_fracture": False,
                "fracture_between": None,
                "type": "未断裂",
                "location": None,
                "confidence": 0.5,
            })
        return LlamaFactoryInferenceClient(
            model=self.config.get("backend", {}).get("name", "minicpmv4_5"),
        )
