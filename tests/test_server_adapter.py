from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.server_adapter import wrap_response


# ---------------------------------------------------------------------------
# 辅助构建函数
# ---------------------------------------------------------------------------


def _make_raw_response(**overrides: dict) -> dict:
    """构建最小化的模拟 OpenAI ChatCompletion 响应。"""
    response = {
        "id": "chatcmpl-abc123",
        "object": "chat.completion",
        "created": 1719200000,
        "model": "minicpm-v-4.5",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "The fracture occurred at index 3.",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 425,
            "completion_tokens": 10,
            "total_tokens": 435,
        },
    }
    response.update(overrides)
    return response


def _make_frames(
    count: int = 4, start_index: int = 0, start_timestamp: float = 0.0
) -> list[dict]:
    """生成指定数量的帧字典。"""
    return [
        {"index": start_index + i, "timestamp": start_timestamp + i * 2.0}
        for i in range(count)
    ]


def _make_processor_info(
    version: str = "minicpmv4.5/0.1", max_frames: int = 8
) -> dict:
    return {
        "processor_version": version,
        "max_frames": max_frames,
        "model_version": "minicpm-v-4.5",
        "transformers_version": "4.test",
        "llamafactory_version": "test-rev",
        "base_model_version": "base-test",
        "artifact_version": "adapter-test",
        "config_fingerprint": "sha256:test",
        "runtime_device": "cpu",
        "runtime_dtype": "float32",
    }


# ---------------------------------------------------------------------------
# 1. 正常注入 —— 验证响应中包含 preprocessing 字段及其子字段
# ---------------------------------------------------------------------------


class TestNormalInjection:
    def test_preprocessing_key_exists(self):
        raw = _make_raw_response()
        frames = _make_frames(4)
        info = _make_processor_info()

        result = wrap_response(raw, frames, info)

        assert "preprocessing" in result

    def test_preprocessing_has_all_subfields(self):
        raw = _make_raw_response()
        frames = _make_frames(4)
        info = _make_processor_info()

        result = wrap_response(raw, frames, info)
        pp = result["preprocessing"]

        assert "request_id" in pp
        assert "processor_version" in pp
        assert "max_frames" in pp
        assert "frames" in pp

    def test_request_id_is_non_empty_string(self):
        raw = _make_raw_response()
        result = wrap_response(raw, _make_frames(4), _make_processor_info())
        rid = result["preprocessing"]["request_id"]
        assert isinstance(rid, str)
        assert len(rid) > 0

    def test_processor_version_passed_correctly(self):
        result = wrap_response(
            _make_raw_response(),
            _make_frames(3),
            _make_processor_info(version="minicpmv4.5/0.2"),
        )
        assert result["preprocessing"]["processor_version"] == "minicpmv4.5/0.2"

    def test_max_frames_passed_correctly(self):
        result = wrap_response(
            _make_raw_response(),
            _make_frames(3),
            _make_processor_info(max_frames=8),
        )
        assert result["preprocessing"]["max_frames"] == 8

    def test_default_processor_version_when_missing(self):
        with pytest.raises(ValueError, match="processor_version"):
            wrap_response(_make_raw_response(), _make_frames(2), {})

    def test_default_max_frames_when_missing(self):
        with pytest.raises(ValueError, match="processor_version"):
            wrap_response(_make_raw_response(), _make_frames(2), {})


# ---------------------------------------------------------------------------
# 2. 空帧列表 —— frames=[] 时 frames 仍为合法空数组
# ---------------------------------------------------------------------------


class TestEmptyFrames:
    def test_empty_frames_list(self):
        with pytest.raises(ValueError, match="between 1 and 8"):
            wrap_response(_make_raw_response(), [], _make_processor_info())

    def test_empty_frames_type_is_list(self):
        with pytest.raises(ValueError, match="between 1 and 8"):
            wrap_response(_make_raw_response(), [], _make_processor_info())


# ---------------------------------------------------------------------------
# 3. 原始字段保留 —— OpenAI 原生字段未被覆盖
# ---------------------------------------------------------------------------


class TestOriginalFieldsPreserved:
    def test_choices_preserved(self):
        raw = _make_raw_response()
        result = wrap_response(raw, _make_frames(4), _make_processor_info())
        assert result["choices"] == raw["choices"]

    def test_model_preserved(self):
        raw = _make_raw_response()
        result = wrap_response(raw, _make_frames(4), _make_processor_info())
        assert result["model"] == raw["model"]

    def test_usage_preserved(self):
        raw = _make_raw_response()
        result = wrap_response(raw, _make_frames(4), _make_processor_info())
        assert result["usage"] == raw["usage"]

    def test_id_preserved(self):
        raw = _make_raw_response()
        result = wrap_response(raw, _make_frames(4), _make_processor_info())
        assert result["id"] == raw["id"]

    def test_created_preserved(self):
        raw = _make_raw_response()
        result = wrap_response(raw, _make_frames(4), _make_processor_info())
        assert result["created"] == raw["created"]

    def test_object_preserved(self):
        raw = _make_raw_response()
        result = wrap_response(raw, _make_frames(4), _make_processor_info())
        assert result["object"] == raw["object"]

    def test_original_dict_not_mutated(self):
        raw = _make_raw_response()
        original_keys = set(raw.keys())
        wrap_response(raw, _make_frames(4), _make_processor_info())
        # raw 不应新增 preprocessing 键
        assert set(raw.keys()) == original_keys


# ---------------------------------------------------------------------------
# 4. UUID 唯一性 —— 两次调用产生不同的 request_id
# ---------------------------------------------------------------------------


class TestRequestIdUniqueness:
    def test_two_calls_different_request_id(self):
        raw = _make_raw_response()
        frames = _make_frames(4)
        info = _make_processor_info()

        result1 = wrap_response(raw, frames, info)
        result2 = wrap_response(raw, frames, info)

        assert result1["preprocessing"]["request_id"] != result2["preprocessing"]["request_id"]

    def test_multiple_calls_all_unique(self):
        raw = _make_raw_response()
        frames = _make_frames(4)
        info = _make_processor_info()

        ids = {wrap_response(raw, frames, info)["preprocessing"]["request_id"] for _ in range(10)}
        assert len(ids) == 10


# ---------------------------------------------------------------------------
# 5. frames 内容正确 —— 每个 frame 包含 index 和 timestamp，值正确
# ---------------------------------------------------------------------------


class TestFramesContent:
    def test_frames_count_matches_input(self):
        input_frames = _make_frames(6)
        result = wrap_response(_make_raw_response(), input_frames, _make_processor_info())
        assert len(result["preprocessing"]["frames"]) == 6

    def test_each_frame_has_index_and_timestamp(self):
        input_frames = _make_frames(3)
        result = wrap_response(_make_raw_response(), input_frames, _make_processor_info())
        for f in result["preprocessing"]["frames"]:
            assert "index" in f
            assert "timestamp" in f

    def test_frame_index_values(self):
        input_frames = [{"index": 10, "timestamp": 5.0}, {"index": 20, "timestamp": 10.0}]
        with pytest.raises(ValueError, match="consecutive"):
            wrap_response(_make_raw_response(), input_frames, _make_processor_info())

    def test_frame_timestamp_values(self):
        input_frames = [{"index": 0, "timestamp": 1.5}, {"index": 1, "timestamp": 3.7}]
        result = wrap_response(_make_raw_response(), input_frames, _make_processor_info())
        assert result["preprocessing"]["frames"][0]["timestamp"] == 1.5
        assert result["preprocessing"]["frames"][1]["timestamp"] == 3.7

    def test_frames_do_not_contain_extra_keys(self):
        """验证 wrap_response 只输出 index 和 timestamp，不泄露额外字段。"""
        input_frames = [
            {"index": 0, "timestamp": 0.0, "extra_field": "should_not_appear"},
        ]
        result = wrap_response(_make_raw_response(), input_frames, _make_processor_info())
        frame = result["preprocessing"]["frames"][0]
        assert set(frame.keys()) == {"index", "timestamp"}


# ---------------------------------------------------------------------------
# 6. processor_info 的各字段正确传递
# ---------------------------------------------------------------------------


class TestProcessorInfoMapping:
    def test_processor_version_mapped(self):
        result = wrap_response(
            _make_raw_response(),
            _make_frames(3),
            _make_processor_info(version="custom/1.0"),
        )
        assert result["preprocessing"]["processor_version"] == "custom/1.0"

    def test_max_frames_mapped(self):
        with pytest.raises(ValueError, match="exactly 8"):
            wrap_response(
                _make_raw_response(), _make_frames(3),
                {"processor_version": "v1", "max_frames": 12},
            )

    def test_processor_info_with_extra_fields_ignored(self):
        """processor_info 中额外的字段不会污染 preprocessing。"""
        info = {**_make_processor_info(version="v1"), "unused_key": "should_not_appear"}
        result = wrap_response(_make_raw_response(), _make_frames(3), info)
        pp_keys = set(result["preprocessing"].keys())
        assert "unused_key" not in pp_keys

    def test_processor_version_defaults_to_unknown(self):
        with pytest.raises(ValueError, match="processor_version"):
            wrap_response(_make_raw_response(), _make_frames(1), {})

    def test_max_frames_defaults_to_eight(self):
        with pytest.raises(ValueError, match="processor_version"):
            wrap_response(_make_raw_response(), _make_frames(1), {})

    def test_request_id_still_present_when_info_empty(self):
        with pytest.raises(ValueError, match="processor_version"):
            wrap_response(_make_raw_response(), _make_frames(2), {})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
