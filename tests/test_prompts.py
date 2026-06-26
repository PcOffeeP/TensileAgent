from __future__ import annotations

import pytest

from agent.prompts import SYSTEM_PROMPT, build_user_prompt


def test_system_prompt_contains_five_fields():
    assert "has_fracture" in SYSTEM_PROMPT
    assert "fracture_between" in SYSTEM_PROMPT
    assert "type" in SYSTEM_PROMPT
    assert "location" in SYSTEM_PROMPT
    assert "confidence" in SYSTEM_PROMPT


def test_system_prompt_contains_eight_frames():
    assert "8 帧" in SYSTEM_PROMPT or "8帧" in SYSTEM_PROMPT
    assert "VIDEO_MAXLEN=8" in SYSTEM_PROMPT or "最多选择 8 帧" in SYSTEM_PROMPT


def test_system_prompt_does_not_contain_fps_or_thirty_six():
    assert "video_fps" not in SYSTEM_PROMPT
    assert "video_maxlen=36" not in SYSTEM_PROMPT
    assert "36 帧" not in SYSTEM_PROMPT
    assert "实际采样" not in SYSTEM_PROMPT


def test_system_prompt_covers_five_legal_combinations():
    assert "正常断裂且可定位" in SYSTEM_PROMPT
    assert "确认未断裂" in SYSTEM_PROMPT
    assert "未夹紧" in SYSTEM_PROMPT
    assert "无法确定是否断裂" in SYSTEM_PROMPT
    assert "确认断裂但时间不可靠" in SYSTEM_PROMPT


def test_build_user_prompt_contains_range_but_no_video_placeholder():
    prompt = build_user_prompt(sample_range=[143.9, 146.9])
    assert "<video>" not in prompt
    assert "[143.9, 146.9]" in prompt


def test_build_user_prompt_contains_eight_frames():
    prompt = build_user_prompt(sample_range=[143.9, 146.9])
    assert "8" in prompt
    assert "视频处理器" in prompt


def test_build_user_prompt_does_not_contain_fps_or_thirty_six():
    prompt = build_user_prompt(sample_range=[143.9, 146.9])
    assert "video_fps" not in prompt
    assert "video_maxlen=36" not in prompt
    assert "36" not in prompt
    assert "实际采样" not in prompt


def test_build_user_prompt_rejects_retired_video_maxlen():
    with pytest.raises(TypeError):
        build_user_prompt(sample_range=[0.0, 10.0], video_maxlen=4)  # type: ignore[call-arg]
