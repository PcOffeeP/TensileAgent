from __future__ import annotations

import pytest

from agent.prompts import PRODUCTION_USER_PROMPT, PROMPT_CONTRACT_HASH, SYSTEM_PROMPT, build_user_prompt


def test_system_prompt_contains_exact_four_field_contract():
    assert "has_fracture" in SYSTEM_PROMPT
    assert "fracture_between" in SYSTEM_PROMPT
    assert "type" in SYSTEM_PROMPT
    assert "location" in SYSTEM_PROMPT
    assert "confidence" not in SYSTEM_PROMPT
    assert "四个字段" in SYSTEM_PROMPT


def test_contract_hash_is_sha256():
    assert len(PROMPT_CONTRACT_HASH) == 64


def test_system_prompt_does_not_contain_fps_or_thirty_six():
    assert "video_fps" not in SYSTEM_PROMPT
    assert "video_maxlen=36" not in SYSTEM_PROMPT
    assert "36 帧" not in SYSTEM_PROMPT
    assert "实际采样" not in SYSTEM_PROMPT


def test_build_user_prompt_is_fixed_across_ranges():
    first = build_user_prompt(sample_range=[143.9, 146.9])
    second = build_user_prompt(sample_range=[0.0, 10.0])
    assert first == second == PRODUCTION_USER_PROMPT
    assert "<video>" not in first
    assert "143.9" not in first


def test_build_user_prompt_does_not_contain_fps_or_thirty_six():
    prompt = build_user_prompt(sample_range=[143.9, 146.9])
    assert "video_fps" not in prompt
    assert "video_maxlen=36" not in prompt
    assert "36" not in prompt
    assert "实际采样" not in prompt


def test_build_user_prompt_rejects_retired_video_maxlen():
    with pytest.raises(TypeError):
        build_user_prompt(sample_range=[0.0, 10.0], video_maxlen=4)  # type: ignore[call-arg]
