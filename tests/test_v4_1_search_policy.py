from __future__ import annotations

from agent.iterative_agent import IterativeAgent


def _agent() -> IterativeAgent:
    agent = object.__new__(IterativeAgent)
    agent.video_meta = {"duration": 100.0}
    agent.candidate = [20.0, 80.0]
    agent.state = "NARROWING"
    agent.tolerance = 1.0
    agent.coverage_index = 0
    agent.no_fracture_count = 0
    agent.pending_recheck_range = None
    agent.focus_miss_count = 0
    agent.localization_index = 0
    agent.low_conf_count = 0
    agent.conflict_count = 0
    agent.last_round_confidence_level = "不可信"
    return agent


def _result(state: str, sample_range: list[float]) -> dict:
    return {
        "ok": True,
        "sample_range": sample_range,
        "model_output": {
            "clip_state": state,
            "fracture_mechanism": None,
            "fracture_site": None,
            "special_case": None,
        },
        "round_confidence_level": "高",
    }


def test_v4_1_unbroken_and_incipient_only_search_later() -> None:
    for state in ("未断裂", "临界未断裂"):
        agent = _agent()
        result = _result(state, [30.0, 45.0])
        agent._transition_v4_1(result, result["model_output"])
        assert agent.candidate == [45.0, 80.0]
        assert result["v4_1_search_direction"] == "later"


def test_v4_1_already_fractured_only_searches_earlier() -> None:
    agent = _agent()
    result = _result("已断裂", [50.0, 65.0])
    agent._transition_v4_1(result, result["model_output"])
    assert agent.candidate == [20.0, 50.0]
    assert result["v4_1_search_direction"] == "earlier"


def test_v4_1_fracturing_uses_agent_owned_clip_interval() -> None:
    agent = _agent()
    result = _result("发生断裂", [35.0, 42.0])
    agent._transition_v4_1(result, result["model_output"])
    assert agent.candidate == [35.0, 42.0]
    assert result["inferred_time_range"] == [35.0, 42.0]
    assert result["v4_1_search_direction"] == "within"


def test_v4_1_unknown_never_creates_search_direction() -> None:
    agent = _agent()
    agent._update_special_recheck = lambda _result: None
    result = _result("无法判断", [35.0, 42.0])
    agent._transition_v4_1(result, result["model_output"])
    assert agent.candidate == [20.0, 80.0]
    assert "v4_1_search_direction" not in result
