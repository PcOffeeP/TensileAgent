"""Strict parser for the tensile-vlm/v4.1 four-field clip contract."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from agent.parser import ParseError, ParseResult, ResultParser


CLIP_STATES = {"未断裂", "临界未断裂", "发生断裂", "已断裂", "无法判断"}
FRACTURE_MECHANISMS = {
    "韧性断裂",
    "脆性断裂",
    "界面脱粘",
    "爆炸性断裂",
    "半脆半韧断裂",
}
FRACTURE_SITES = {"inside_gauge", "outside_gauge_non_root", "grip_root"}
SPECIAL_CASES = {"未夹紧", "视频异常"}


class V4_1ModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    clip_state: str
    fracture_mechanism: str | None
    fracture_site: str | None
    special_case: str | None

    @model_validator(mode="after")
    def _validate_combinations(self) -> "V4_1ModelOutput":
        if self.clip_state not in CLIP_STATES:
            raise ValueError("clip_state is outside the V4.1 enum")
        if (
            self.fracture_mechanism is not None
            and self.fracture_mechanism not in FRACTURE_MECHANISMS
        ):
            raise ValueError("fracture_mechanism is outside the V4.1 enum")
        if self.fracture_site is not None and self.fracture_site not in FRACTURE_SITES:
            raise ValueError("fracture_site is outside the V4.1 enum")
        if self.special_case is not None and self.special_case not in SPECIAL_CASES:
            raise ValueError("special_case is outside the V4.1 enum")
        if self.clip_state == "未断裂" and any(
            value is not None
            for value in (
                self.fracture_mechanism,
                self.fracture_site,
                self.special_case,
            )
        ):
            raise ValueError("未断裂 requires all other fields to be null")
        if self.clip_state == "临界未断裂":
            if self.fracture_mechanism not in {None, "韧性断裂"}:
                raise ValueError("临界未断裂 mechanism must be 韧性断裂 or null")
            if self.special_case is not None:
                raise ValueError("临界未断裂 special_case must be null")
        if self.special_case is not None and (
            self.clip_state != "无法判断"
            or self.fracture_mechanism is not None
            or self.fracture_site is not None
        ):
            raise ValueError("special_case requires 无法判断 and null fracture fields")
        return self


class V4_1ResultParser:
    """Return the same ParseResult envelope as the legacy strict parser."""

    ERROR_INVALID_MODEL_OUTPUT = ResultParser.ERROR_INVALID_MODEL_OUTPUT

    @classmethod
    def parse(cls, raw_text: str) -> ParseResult:
        text = (raw_text or "").strip()
        if not text:
            return ParseResult(
                ok=False,
                error=ParseError(ResultParser.ERROR_EMPTY_INPUT, "input is empty"),
            )
        if text.startswith("```") or text.endswith("```"):
            return ParseResult(
                ok=False,
                error=ParseError(
                    ResultParser.ERROR_MARKDOWN_NOT_ALLOWED,
                    "assistant content must not be wrapped in Markdown fences",
                ),
            )
        try:
            value: Any = json.loads(text)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            return ParseResult(
                ok=False,
                error=ParseError(
                    ResultParser.ERROR_INVALID_JSON, f"invalid JSON: {exc}"
                ),
            )
        if not isinstance(value, dict):
            return ParseResult(
                ok=False,
                error=ParseError(
                    ResultParser.ERROR_NOT_A_JSON_OBJECT,
                    "assistant content must be a JSON object",
                ),
            )
        expected = {
            "clip_state",
            "fracture_mechanism",
            "fracture_site",
            "special_case",
        }
        missing = expected - value.keys()
        if missing:
            field = sorted(missing)[0]
            return ParseResult(
                ok=False,
                error=ParseError(
                    ResultParser.ERROR_MISSING_FIELD,
                    f"missing required field(s): {sorted(missing)}",
                    field,
                ),
            )
        extra = value.keys() - expected
        if extra:
            field = sorted(extra)[0]
            return ParseResult(
                ok=False,
                error=ParseError(
                    ResultParser.ERROR_EXTRA_FIELD,
                    f"extra field(s) not allowed: {sorted(extra)}",
                    field,
                ),
            )
        try:
            parsed = V4_1ModelOutput.model_validate(value)
        except Exception as exc:  # noqa: BLE001
            return ParseResult(
                ok=False,
                error=ParseError(
                    ResultParser.ERROR_INVALID_COMBINATION,
                    str(exc),
                ),
            )
        return ParseResult(ok=True, data=parsed.model_dump())
