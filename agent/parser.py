"""Strict model-response parser with stable error codes and correction retries.

The parser implements the v2 contract:

* The assistant content must be a single JSON object with exactly the five
  contract fields.
* Markdown fences, surrounding prose, JSON extraction from noise, missing
  fields, extra fields and illegal value combinations are all rejected.
* Errors are reported through stable ``ParseError`` codes so that callers can
  build deterministic correction prompts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from agent.schema import ModelOutput


@dataclass
class ParseError:
    """Structured parser error with a stable machine-readable code."""

    code: str
    message: str
    field: str | None = None


@dataclass
class ParseResult:
    """Result of parsing a single raw model response."""

    ok: bool
    data: dict[str, Any] | None = None
    error: ParseError | None = None
    attempts: int = 1


class ResultParser:
    """Strict parser for fine-tuned model assistant content."""

    ERROR_EMPTY_INPUT = "empty_input"
    ERROR_MARKDOWN_NOT_ALLOWED = "markdown_not_allowed"
    ERROR_INVALID_JSON = "invalid_json"
    ERROR_NOT_A_JSON_OBJECT = "not_a_json_object"
    ERROR_MISSING_FIELD = "missing_field"
    ERROR_EXTRA_FIELD = "extra_field"
    ERROR_INVALID_FIELD_TYPE = "invalid_field_type"
    ERROR_INVALID_TYPE_VALUE = "invalid_type_value"
    ERROR_INVALID_LOCATION_VALUE = "invalid_location_value"
    ERROR_INVALID_CONFIDENCE = "invalid_confidence"
    ERROR_INVALID_INDEX = "invalid_index"
    ERROR_INVALID_COMBINATION = "invalid_combination"
    ERROR_INVALID_MODEL_OUTPUT = "invalid_model_output"

    _CONTRACT_FIELDS = {
        "has_fracture",
        "fracture_between",
        "type",
        "location",
        "confidence",
    }

    @classmethod
    def parse(cls, raw_text: str) -> ParseResult:
        """Parse and validate ``raw_text`` against the v2 model output schema.

        Returns a ``ParseResult``.  On failure ``ok`` is ``False`` and
        ``error`` contains a stable code plus a human-readable message.
        """
        text = (raw_text or "").strip()
        if not text:
            return cls._error(cls.ERROR_EMPTY_INPUT, "input is empty")

        if cls._is_markdown_fenced(text):
            return cls._error(
                cls.ERROR_MARKDOWN_NOT_ALLOWED,
                "assistant content must not be wrapped in Markdown fences",
            )

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            return cls._error(cls.ERROR_INVALID_JSON, f"invalid JSON: {exc}")

        if not isinstance(data, dict):
            return cls._error(
                cls.ERROR_NOT_A_JSON_OBJECT, "assistant content must be a JSON object"
            )

        # Exact field set check before delegating to Pydantic so that missing
        # and extra fields receive distinct stable codes.
        missing = cls._CONTRACT_FIELDS - data.keys()
        if missing:
            return cls._error(
                cls.ERROR_MISSING_FIELD,
                f"missing required field(s): {sorted(missing)}",
                field=sorted(missing)[0],
            )

        extra = data.keys() - cls._CONTRACT_FIELDS
        if extra:
            return cls._error(
                cls.ERROR_EXTRA_FIELD,
                f"extra field(s) not allowed: {sorted(extra)}",
                field=sorted(extra)[0],
            )

        try:
            validated = ModelOutput(**data)
        except Exception as exc:  # noqa: BLE001
            return cls._map_pydantic_error(exc)

        return ParseResult(ok=True, data=validated.model_dump(), error=None)

    @classmethod
    def parse_with_retries(
        cls,
        fetch_fn: Callable[[ParseError | None], str],
        max_retries: int = 2,
    ) -> ParseResult:
        """Parse with up to ``max_retries`` correction attempts.

        ``fetch_fn`` receives the previous ``ParseError`` (``None`` on the
        first attempt) and must return the raw assistant content to parse.
        The returned ``ParseResult`` records the number of attempts actually
        consumed.
        """
        last_error: ParseError | None = None
        for attempt in range(max_retries + 1):
            raw = fetch_fn(last_error)
            result = cls.parse(raw)
            if result.ok:
                result.attempts = attempt + 1
                return result
            last_error = result.error

        result = cls._error(
            cls.ERROR_INVALID_MODEL_OUTPUT,
            f"model output remained invalid after {max_retries} correction retries",
        )
        result.attempts = max_retries + 1
        return result

    @staticmethod
    def _is_markdown_fenced(text: str) -> bool:
        """Detect `` ```json ... ``` `` or plain `` ``` ... ``` `` fences."""
        return text.startswith("```") or text.endswith("```")

    @classmethod
    def _error(cls, code: str, message: str, field: str | None = None) -> ParseResult:
        return ParseResult(ok=False, error=ParseError(code=code, message=message, field=field))

    @classmethod
    def _map_pydantic_error(cls, exc: Exception) -> ParseResult:
        """Map a Pydantic ``ValidationError`` to a stable parser error code."""
        from pydantic import ValidationError

        if not isinstance(exc, ValidationError):
            return cls._error(cls.ERROR_INVALID_COMBINATION, str(exc))

        first = exc.errors()[0]
        loc = first.get("loc", ())
        ctx_error = first.get("ctx", {}).get("error")
        message = str(ctx_error) if ctx_error is not None else first.get("msg", str(exc))
        field = str(loc[0]) if loc else None
        error_type = first.get("type", "")

        if error_type == "extra_forbidden":
            return cls._error(cls.ERROR_EXTRA_FIELD, message, field=field)
        if error_type == "missing":
            return cls._error(cls.ERROR_MISSING_FIELD, message, field=field)

        # Field-level errors carry a non-empty loc.
        if field:
            return cls._map_field_error(field, message)

        # Model-level value errors: recover the field from the message prefix.
        if message.startswith("fracture_between"):
            return cls._error(cls.ERROR_INVALID_INDEX, message, field="fracture_between")
        if message.startswith("confidence"):
            return cls._error(cls.ERROR_INVALID_CONFIDENCE, message, field="confidence")
        if message.startswith("location"):
            return cls._error(cls.ERROR_INVALID_LOCATION_VALUE, message, field="location")
        if message.startswith("type"):
            return cls._error(cls.ERROR_INVALID_TYPE_VALUE, message, field="type")
        if message.startswith("has_fracture"):
            return cls._error(cls.ERROR_INVALID_FIELD_TYPE, message, field="has_fracture")

        return cls._error(cls.ERROR_INVALID_COMBINATION, message)

    @classmethod
    def _map_field_error(cls, field: str, message: str) -> ParseResult:
        """Map a field-level validation error to a stable code."""
        if field == "confidence":
            return cls._error(cls.ERROR_INVALID_CONFIDENCE, message, field=field)
        if field == "fracture_between":
            return cls._error(cls.ERROR_INVALID_INDEX, message, field=field)
        if field == "location":
            return cls._error(cls.ERROR_INVALID_LOCATION_VALUE, message, field=field)
        if field == "type":
            return cls._error(cls.ERROR_INVALID_TYPE_VALUE, message, field=field)
        if field == "has_fracture":
            return cls._error(cls.ERROR_INVALID_FIELD_TYPE, message, field=field)
        return cls._error(cls.ERROR_INVALID_COMBINATION, message, field=field)
