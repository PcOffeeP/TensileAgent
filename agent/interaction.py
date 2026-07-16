"""Natural-language intent parsing and user-facing result projection."""

from __future__ import annotations

import re
from typing import Any

from agent.schema import UserIntent


_ALL_FIELDS = [
    "has_fracture",
    "time_range",
    "type",
    "location",
    "confidence",
    "visual_evidence",
]


def parse_user_intent(question: str | None) -> UserIntent:
    """Parse common Chinese/English tensile-analysis questions deterministically.

    The original question is used only here. It is never included in the
    visual-model message list.
    """
    text = (question or "请完整分析这段拉伸试验视频").strip()
    lower = text.lower()
    for typo, canonical in {
        "断列": "断裂",
        "段裂": "断裂",
        "位直": "位置",
        "类形": "类型",
    }.items():
        lower = lower.replace(typo, canonical)
    language = "en" if re.search(r"[a-zA-Z]", text) and not re.search(r"[\u4e00-\u9fff]", text) else "zh"

    requested: list[str] = []
    if re.search(r"断(了|裂|没)|是否.*断|fracture|broken|break", lower):
        requested.append("has_fracture")
    if re.search(r"什么时候|啥时候|何时|几秒|多少秒|哪一秒|第几秒|几点|时间|哪.*帧|区间|when|what second|time|frame", lower):
        requested.append("time_range")
    if re.search(r"类型|模式|种类|哪种|什么断裂|type|mode|kind", lower):
        requested.append("type")
    if re.search(r"位置|哪里|哪儿|什么地方|哪个地方|哪个部位|断在哪|断裂点|标距|location|where|which part", lower):
        requested.append("location")
    if re.search(r"置信|把握|确定吗|可靠|confidence|sure|certain", lower):
        requested.append("confidence")
    if re.search(r"为什么|依据|证据|怎么看|reason|evidence|why", lower):
        requested.append("visual_evidence")

    detailed = bool(re.search(r"完整|全面|详细|综合|all|full|detail|comprehensive", lower))
    if detailed:
        requested = list(_ALL_FIELDS)
    elif not requested:
        # A generic request such as “帮我看一下” is treated as a concise full
        # analysis, while clearly unrelated text is reported as unsupported.
        if re.search(r"分析|看看|看一下|视频|试样|拉伸|analy[sz]e|video|tensile", lower):
            requested = ["has_fracture", "time_range", "type", "location"]
        else:
            return UserIntent(
                action="unsupported",
                requested_fields=["has_fracture"],
                language=language,
                ambiguity="未识别到拉伸试验视频分析需求",
            )

    return UserIntent(
        requested_fields=list(dict.fromkeys(requested)),
        wants_evidence="visual_evidence" in requested,
        wants_confidence="confidence" in requested,
        response_detail="detailed" if detailed else "concise",
        language=language,
    )


def project_result(result: dict[str, Any], intent: UserIntent) -> dict[str, Any]:
    """Project a complete Agent conclusion onto the fields the user requested."""
    if intent.action == "unsupported":
        return {
            "status": "unrecognized",
            "answer": None,
            "evidence_available": False,
            "error": {"code": "unsupported_intent", "message": intent.ambiguity},
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

    has_fracture = True if status == "fracture" else False
    complete = {
        "has_fracture": has_fracture,
        "time_range": result.get("time_range"),
        "type": result.get("fracture_type"),
        "location": result.get("location"),
        "confidence": result.get("confidence"),
        "visual_evidence": result.get("visual_evidence"),
    }
    answer = {field: complete[field] for field in intent.requested_fields}
    evidence = result.get("visual_evidence") or {}
    return {
        "status": "answered",
        "answer": answer,
        "evidence_available": evidence.get("status") == "available",
        "error": None,
    }
