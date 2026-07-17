from __future__ import annotations

from agent.prompts import (
    META_AGENT_SYSTEM_PROMPT,
    build_meta_agent_user_context,
    build_sample_and_infer_prompt,
)


def test_meta_agent_system_prompt_contains_rules():
    assert "材料拉伸试验视频分析协调者" in META_AGENT_SYSTEM_PROMPT
    assert "sample_and_infer" in META_AGENT_SYSTEM_PROMPT
    assert "terminate" in META_AGENT_SYSTEM_PROMPT
    assert "必须通过 `tool_calls` 输出你的决策" in META_AGENT_SYSTEM_PROMPT


def test_build_meta_agent_user_context_contains_video_meta():
    video_meta = {"video_id": "v001", "duration": 120.0, "fps": 30.0, "total_frames": 3600}
    config = {"agent": {"tolerance_seconds": 1.0, "max_rounds": 10, "video_fps": 8.0, "video_maxlen": 36}}
    context = build_meta_agent_user_context(
        video_meta=video_meta,
        config=config,
        current_round=1,
        candidate=[0.0, 120.0],
        history=[],
    )
    assert "v001" in context
    assert "120.0s" in context
    assert "容忍误差: 1.0s" in context
    assert "当前候选区间: [0.0, 120.0]s" in context


def test_build_meta_agent_user_context_includes_history():
    video_meta = {"video_id": "v001", "duration": 100.0, "fps": 30.0, "total_frames": 3000}
    config = {"agent": {"tolerance_seconds": 1.0, "max_rounds": 5, "video_fps": 8.0, "video_maxlen": 36}}
    history = [
        {
            "round": 0,
            "result": {
                "sample_range": [0.0, 100.0],
                "model_output": {"has_fracture": True, "fracture_between": [17, 18]},
                "inferred_time_range": [48.57, 51.43],
            },
        }
    ]
    context = build_meta_agent_user_context(
        video_meta=video_meta,
        config=config,
        current_round=2,
        candidate=[48.57, 51.43],
        history=history,
    )
    assert "evidence_index=0（Agent轮次1）:" in context
    assert "evidence_rounds" in META_AGENT_SYSTEM_PROMPT
    assert "evidence_index" in META_AGENT_SYSTEM_PROMPT
    assert "[0.0, 100.0]s" in context
    assert "[48.57, 51.43]s" in context


def test_build_sample_and_infer_prompt_has_required_elements():
    config = {"agent": {"video_fps": 8.0, "video_maxlen": 36}}
    prompt = build_sample_and_infer_prompt(sample_range=[10.0, 20.0], config=config)
    # Contract: runtime user prompt does NOT contain <video> literal
    assert "<video>" not in prompt
    # Production prompt is fixed; range and runtime sampling details stay out.
    assert "[10.0, 20.0]" not in prompt
    # v2 prompt does not expose FPS or video_maxlen as key=value
    assert "video_fps" not in prompt
    assert "video_maxlen=" not in prompt
    # v2 prompt does not use the old "实际采样" phrasing
    assert "实际采样" not in prompt
    assert prompt == build_sample_and_infer_prompt(sample_range=[0.0, 5.0], config={})
