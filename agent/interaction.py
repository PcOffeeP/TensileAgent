"""Natural-language intent parsing and user-facing result projection."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from agent.config_util import load_config
from agent.llm import AgentLLMFactory
from agent.prompts import (
    INTENT_RECOGNITION_SYSTEM_PROMPT,
    build_intent_recognition_user_prompt,
)
from agent.schema import UserIntent

logger = logging.getLogger(__name__)

_ALL_FIELDS = [
    "has_fracture",
    "time_range",
    "type",
    "location",
    "confidence",
    "visual_evidence",
]

_AMBIGUITY_TEXT: dict[str, str] = {
    "prompt_injection": "请求包含改变系统或视觉协议的指令，已在推理前拒绝",
    "contradictory_intent": "请求同时要求分析与不分析",
    "analysis_declined": "用户明确要求不执行视频分析",
    "unsupported_intent": "未识别到拉伸试验视频分析需求",
    "out_of_scope": (
        "该问题超出当前分析能力范围。当前支持：断裂检测、断裂时间定位、"
        "断口类型与位置分析、置信度与图像证据。请围绕拉伸试验视频的分析需求提问。"
    ),
}

_INTENT_MAX_TOKENS = 512


class _IntentConsistencyError(ValueError):
    """Raised when a model output fails the code-level consistency review."""


class _IntentModelUnavailableError(RuntimeError):
    """Raised when the intent model cannot be reached or returns unusable output."""


def _detect_language(text: str) -> str:
    return (
        "en"
        if re.search(r"[a-zA-Z]", text) and not re.search(r"[\u4e00-\u9fff]", text)
        else "zh"
    )


def _normalize_text(text: str) -> str:
    lower = text.lower()
    for typo, canonical in {
        "断列": "断裂",
        "段裂": "断裂",
        "位直": "位置",
        "类形": "类型",
    }.items():
        lower = lower.replace(typo, canonical)
    return lower


def _security_review(text: str) -> tuple[bool, str | None, str | None]:
    """Run the deterministic safety regexes over the raw user text.

    Returns (hit, rejection_code, ambiguity). A hit means the caller must
    override the model decision with ``action="unsupported"`` and the returned
    code/ambiguity, without falling back to the regex path.
    """
    lower = _normalize_text(text)

    injection = re.search(
        r"忽略.{0,12}(指令|规则|系统)|覆盖.{0,8}(提示|prompt)|系统提示|"
        r"ignore.{0,12}(previous|system|instruction)|system\s+prompt|jailbreak|"
        r"把.{0,12}(原话|问题).{0,12}(传|发).{0,8}(视觉|模型)",
        lower,
    )
    if injection:
        return True, "prompt_injection", _AMBIGUITY_TEXT["prompt_injection"]

    refusal = re.search(
        r"(不要|无需|别|停止|取消).{0,8}(分析|识别|调用|看)|"
        r"do\s+not\s+(analy[sz]e|inspect|call)|don't\s+(analy[sz]e|inspect|call)",
        lower,
    )
    analysis_request = re.search(
        r"分析|识别|看看|视频|断裂|analy[sz]e|inspect|fracture|video", lower
    )
    if refusal and analysis_request:
        contradictory = bool(
            re.search(
                r"(但|同时|然后|又|however|but).{0,12}(分析|识别|看看|analy[sz]e|inspect)",
                lower,
            )
            or re.search(
                r"(分析|识别|看看|analy[sz]e|inspect).{0,12}(但|同时|however|but).{0,12}(不要|don't)",
                lower,
            )
        )
        if contradictory:
            return True, "contradictory_intent", _AMBIGUITY_TEXT["contradictory_intent"]
        return True, "analysis_declined", _AMBIGUITY_TEXT["analysis_declined"]

    return False, None, None


def _regex_parse_user_intent(question: str | None) -> UserIntent:
    """Parse common Chinese/English tensile-analysis questions deterministically.

    The original question is used only here. It is never included in the
    visual-model message list.
    """
    text = (question or "请完整分析这段拉伸试验视频").strip()
    lower = _normalize_text(text)
    language = _detect_language(text)

    injection = re.search(
        r"忽略.{0,12}(指令|规则|系统)|覆盖.{0,8}(提示|prompt)|系统提示|"
        r"ignore.{0,12}(previous|system|instruction)|system\s+prompt|jailbreak|"
        r"把.{0,12}(原话|问题).{0,12}(传|发).{0,8}(视觉|模型)",
        lower,
    )
    refusal = re.search(
        r"(不要|无需|别|停止|取消).{0,8}(分析|识别|调用|看)|"
        r"do\s+not\s+(analy[sz]e|inspect|call)|don't\s+(analy[sz]e|inspect|call)",
        lower,
    )
    analysis_request = re.search(
        r"分析|识别|看看|视频|断裂|analy[sz]e|inspect|fracture|video", lower
    )
    if injection:
        return UserIntent(
            action="unsupported",
            requested_fields=["has_fracture"],
            language=language,
            ambiguity="请求包含改变系统或视觉协议的指令，已在推理前拒绝",
            rejection_code="prompt_injection",
        )
    if refusal and analysis_request:
        contradictory = bool(
            re.search(
                r"(但|同时|然后|又|however|but).{0,12}(分析|识别|看看|analy[sz]e|inspect)",
                lower,
            )
            or re.search(
                r"(分析|识别|看看|analy[sz]e|inspect).{0,12}(但|同时|however|but).{0,12}(不要|don't)",
                lower,
            )
        )
        return UserIntent(
            action="unsupported",
            requested_fields=["has_fracture"],
            language=language,
            ambiguity="请求同时要求分析与不分析"
            if contradictory
            else "用户明确要求不执行视频分析",
            rejection_code="contradictory_intent"
            if contradictory
            else "analysis_declined",
        )

    requested: list[str] = []
    if re.search(r"断(了|裂|没)|是否.*断|fracture|broken|break", lower):
        requested.append("has_fracture")
    if re.search(
        r"什么时候|啥时候|何时|几秒|多少秒|哪一秒|第几秒|几点|时间|哪.*帧|区间|when|what second|time|frame",
        lower,
    ):
        requested.append("time_range")
    if re.search(r"类型|模式|种类|哪种|什么断裂|type|mode|kind", lower):
        requested.append("type")
    if re.search(
        r"位置|哪里|哪儿|什么地方|哪个地方|哪个部位|断在哪|断裂点|标距|location|where|which part",
        lower,
    ):
        requested.append("location")
    if re.search(r"置信|把握|确定吗|可靠|confidence|sure|certain", lower):
        requested.append("confidence")
    if re.search(r"为什么|依据|证据|怎么看|reason|evidence|why", lower):
        requested.append("visual_evidence")

    detailed = bool(
        re.search(r"完整|全面|详细|综合|all|full|detail|comprehensive", lower)
    )
    if detailed:
        requested = list(_ALL_FIELDS)
    elif not requested:
        # A generic request such as “帮我看一下” is treated as a concise full
        # analysis, while clearly unrelated text is reported as unsupported.
        if re.search(
            r"分析|看看|看一下|视频|试样|拉伸|analy[sz]e|video|tensile", lower
        ):
            requested = ["has_fracture", "time_range", "type", "location"]
        else:
            return UserIntent(
                action="unsupported",
                requested_fields=["has_fracture"],
                language=language,
                ambiguity="未识别到拉伸试验视频分析需求",
                rejection_code="unsupported_intent",
            )

    return UserIntent(
        requested_fields=list(dict.fromkeys(requested)),
        wants_evidence="visual_evidence" in requested,
        wants_confidence="confidence" in requested,
        response_detail="detailed" if detailed else "concise",
        language=language,
    )


def _extract_response_text(response: Any) -> str:
    """Best-effort extraction of the model text content."""
    try:
        choices = response.choices
    except AttributeError:
        choices = response.get("choices", [])
    if not choices:
        raise _IntentModelUnavailableError("model response has no choices")
    message = choices[0].message if hasattr(choices[0], "message") else choices[0].get("message", {})
    content = message.content if hasattr(message, "content") else message.get("content", "")
    if not isinstance(content, str):
        content = str(content)
    return content


def _strip_json_markdown(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        # Drop the leading ```json / ``` fence.
        lines = stripped.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def _apply_code_review(intent: UserIntent, question: str) -> UserIntent:
    """Run code-level security and consistency checks over a validated intent."""
    text = (question or "请完整分析这段拉伸试验视频").strip()

    # ① Security review: code overrules the model.
    hit, rejection_code, ambiguity = _security_review(text)
    if hit:
        return UserIntent(
            action="unsupported",
            requested_fields=["has_fracture"],
            language=_detect_language(text),
            ambiguity=ambiguity,
            rejection_code=rejection_code,
        )

    # explain_previous is not consumed in this version; treat as unsupported.
    if intent.action == "explain_previous":
        return UserIntent(
            action="unsupported",
            requested_fields=["has_fracture"],
            language=intent.language,
            ambiguity=_AMBIGUITY_TEXT["unsupported_intent"],
            rejection_code="unsupported_intent",
        )

    # ③ Consistency review.
    if intent.wants_evidence and "visual_evidence" not in intent.requested_fields:
        raise _IntentConsistencyError(
            "wants_evidence=True but requested_fields lacks visual_evidence"
        )
    if intent.wants_confidence and "confidence" not in intent.requested_fields:
        raise _IntentConsistencyError(
            "wants_confidence=True but requested_fields lacks confidence"
        )

    if intent.action == "unsupported":
        if intent.rejection_code == "out_of_scope":
            return UserIntent(
                action="unsupported",
                requested_fields=["has_fracture"],
                language=intent.language,
                ambiguity=_AMBIGUITY_TEXT["out_of_scope"],
                rejection_code="out_of_scope",
            )
        # Any other unsupported reason (or none) is normalized to unsupported_intent.
        return UserIntent(
            action="unsupported",
            requested_fields=["has_fracture"],
            language=intent.language,
            ambiguity=_AMBIGUITY_TEXT["unsupported_intent"],
            rejection_code="unsupported_intent",
        )

    # Normal analyze_video path: clear any leftover unsupported-only fields.
    if intent.rejection_code is not None or intent.ambiguity is not None:
        return UserIntent(
            action=intent.action,
            requested_fields=list(intent.requested_fields),
            wants_evidence=intent.wants_evidence,
            wants_confidence=intent.wants_confidence,
            response_detail=intent.response_detail,
            language=intent.language,
            ambiguity=None,
            rejection_code=None,
        )
    return intent


def parse_user_intent(question: str | None) -> UserIntent:
    """Parse user intent via model + code review, with deterministic fallback."""
    text = (question or "请完整分析这段拉伸试验视频").strip()
    config = load_config()
    backend = config.get("agent", {}).get("backend", "remote")
    if backend == "deterministic":
        return _regex_parse_user_intent(question)

    try:
        client = AgentLLMFactory.create(config)
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": INTENT_RECOGNITION_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": build_intent_recognition_user_prompt(text),
            },
        ]
        response = client.chat_with_tools(
            messages=messages,
            tools=[],
            temperature=float(config.get("agent", {}).get("temperature", 0.2)),
            max_tokens=_INTENT_MAX_TOKENS,
        )
        content = _extract_response_text(response)
        content = _strip_json_markdown(content)
        data = json.loads(content)
        if not isinstance(data, dict):
            raise _IntentModelUnavailableError("model output is not a JSON object")
        validated = UserIntent(**data)
        return _apply_code_review(validated, text)
    except _IntentConsistencyError:
        logger.debug("Intent consistency review failed; falling back to regex")
        return _regex_parse_user_intent(question)
    except Exception as exc:
        logger.debug("Intent model path failed (%s); falling back to regex", exc)
        return _regex_parse_user_intent(question)


def project_result(result: dict[str, Any], intent: UserIntent) -> dict[str, Any]:
    """Project a complete Agent conclusion onto the fields the user requested."""
    if intent.action == "unsupported":
        return {
            "status": "unrecognized",
            "answer": None,
            "evidence_available": False,
            "error": {
                "code": intent.rejection_code or "unsupported_intent",
                "message": intent.ambiguity,
            },
        }

    status = result.get("status")
    if status == "unrecognized":
        return {
            "status": "unrecognized",
            "answer": {"has_fracture": None},
            "evidence_available": False,
            "error": {
                "code": result.get("unrecognized_reason", "insufficient_evidence"),
                "message": "当前证据不足，无法可靠回答该问题。",
            },
        }

    complete = {
        "has_fracture": result.get("has_fracture"),
        "time_range": result.get("time_range"),
        "type": result.get("fracture_type"),
        "location": result.get("location"),
        "confidence": result.get("confidence"),
        "visual_evidence": result.get("visual_evidence"),
    }
    answer = {field: complete[field] for field in intent.requested_fields}
    status_names = {"type": "fracture_type"}
    field_status = result.get("field_status") or {}
    unavailable = [
        field
        for field in intent.requested_fields
        if field_status.get(status_names.get(field, field)) == "unavailable"
    ]
    evidence = result.get("visual_evidence") or {}
    return {
        "status": "partial" if unavailable else "answered",
        "answer": answer,
        "evidence_available": evidence.get("status") == "available",
        "error": (
            {
                "code": "requested_fields_unavailable",
                "message": f"以下请求字段当前不可用: {', '.join(unavailable)}",
            }
            if unavailable
            else None
        ),
    }
