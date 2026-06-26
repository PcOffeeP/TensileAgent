from __future__ import annotations

import pytest

from agent.parser import ParseError, ParseResult, ResultParser


def test_parse_plain_json():
    raw = '{"has_fracture": true, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92}'
    result = ResultParser.parse(raw)
    assert result.ok is True
    assert result.error is None
    assert result.data == {
        "has_fracture": True,
        "fracture_between": [17, 18],
        "type": "韧性断裂",
        "location": "inside_gauge",
        "confidence": pytest.approx(0.92),
    }


def test_parse_rejects_markdown_fence():
    raw = '```json\n{"has_fracture": false, "fracture_between": null, "type": "未断裂", "location": null, "confidence": 0.88}\n```'
    result = ResultParser.parse(raw)
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == ResultParser.ERROR_MARKDOWN_NOT_ALLOWED


def test_parse_rejects_markdown_fence_plain():
    raw = '```\n{"has_fracture": false, "fracture_between": null, "type": "未断裂", "location": null, "confidence": 0.88}\n```'
    result = ResultParser.parse(raw)
    assert result.ok is False
    assert result.error.code == ResultParser.ERROR_MARKDOWN_NOT_ALLOWED


def test_parse_invalid_json_returns_error():
    result = ResultParser.parse("not json")
    assert result.ok is False
    assert result.error is not None
    assert result.error.code == ResultParser.ERROR_INVALID_JSON


def test_parse_empty_and_none_input():
    result = ResultParser.parse("")
    assert result.ok is False
    assert result.error.code == ResultParser.ERROR_EMPTY_INPUT

    result = ResultParser.parse(None)  # type: ignore[arg-type]
    assert result.ok is False
    assert result.error.code == ResultParser.ERROR_EMPTY_INPUT


def test_parse_rejects_schema_violations():
    # has_fracture=true but type is a non-fracture class.
    raw = '{"has_fracture": true, "fracture_between": [17, 18], "type": "未断裂", "location": "inside_gauge", "confidence": 0.92}'
    result = ResultParser.parse(raw)
    assert result.ok is False
    assert result.error is not None


def test_parse_rejects_confidence_out_of_range():
    raw = '{"has_fracture": true, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 1.5}'
    result = ResultParser.parse(raw)
    assert result.ok is False
    assert result.error.code == ResultParser.ERROR_INVALID_CONFIDENCE


def test_parse_rejects_boolean_confidence():
    raw = '{"has_fracture": true, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": true}'
    result = ResultParser.parse(raw)
    assert result.ok is False
    assert result.error.code == ResultParser.ERROR_INVALID_CONFIDENCE


def test_parse_rejects_extra_fields():
    raw = '{"has_fracture": true, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92, "reasoning": "some extra"}'
    result = ResultParser.parse(raw)
    assert result.ok is False
    assert result.error.code == ResultParser.ERROR_EXTRA_FIELD
    assert result.error.field == "reasoning"


def test_parse_rejects_missing_fields():
    raw = '{"has_fracture": true, "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92}'
    result = ResultParser.parse(raw)
    assert result.ok is False
    assert result.error.code == ResultParser.ERROR_MISSING_FIELD


def test_parse_rejects_noise_extraction():
    raw = 'Some explanation text before {\n  "has_fracture": false,\n  "fracture_between": null,\n  "type": "未夹紧",\n  "location": null,\n  "confidence": 0.7\n} and after.'
    result = ResultParser.parse(raw)
    assert result.ok is False
    assert result.error.code == ResultParser.ERROR_INVALID_JSON


def test_parse_null_has_fracture_semantics():
    raw = '{"has_fracture": null, "fracture_between": null, "type": "视频异常", "location": null, "confidence": 0.7}'
    result = ResultParser.parse(raw)
    assert result.ok is True
    assert result.data["has_fracture"] is None
    assert result.data["type"] == "视频异常"


def test_parse_video_anomaly_with_confirmed_fracture():
    raw = '{"has_fracture": true, "fracture_between": null, "type": "视频异常", "location": null, "confidence": 0.65}'
    result = ResultParser.parse(raw)
    assert result.ok is True
    assert result.data["has_fracture"] is True
    assert result.data["fracture_between"] is None


def test_parse_rejects_non_adjacent_indexes():
    raw = '{"has_fracture": true, "fracture_between": [17, 19], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92}'
    result = ResultParser.parse(raw)
    assert result.ok is False
    assert result.error.code == ResultParser.ERROR_INVALID_INDEX


def test_parse_rejects_not_a_json_object():
    result = ResultParser.parse("[1, 2, 3]")
    assert result.ok is False
    assert result.error.code == ResultParser.ERROR_NOT_A_JSON_OBJECT


def test_parse_with_retries_succeeds_on_second_attempt():
    responses = [
        '{"has_fracture": true, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 1.5}',
        '{"has_fracture": true, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 0.92}',
    ]

    def fetch_fn(_error: ParseError | None) -> str:
        return responses.pop(0)

    result = ResultParser.parse_with_retries(fetch_fn, max_retries=2)
    assert result.ok is True
    assert result.attempts == 2
    assert result.data is not None


def test_parse_with_retries_exhausted():
    bad = '{"has_fracture": true, "fracture_between": [17, 18], "type": "韧性断裂", "location": "inside_gauge", "confidence": 1.5}'

    call_count = 0

    def fetch_fn(_error: ParseError | None) -> str:
        nonlocal call_count
        call_count += 1
        return bad

    result = ResultParser.parse_with_retries(fetch_fn, max_retries=2)
    assert result.ok is False
    assert result.attempts == 3
    assert call_count == 3
    assert result.error is not None


def test_parse_result_dataclass_defaults():
    result = ParseResult(ok=False, error=ParseError(code="x", message="y"))
    assert result.data is None
    assert result.attempts == 1
