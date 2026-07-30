from __future__ import annotations

from agent.iterative_agent import IterativeAgent
from agent.v4_1_evidence import V41EventBounds


def _agent() -> IterativeAgent:
    agent = object.__new__(IterativeAgent)
    agent.video_meta = {"duration": 100.0}
    agent.candidate = [20.0, 80.0]
    agent.event_bounds = V41EventBounds(20.0, 80.0)
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


def test_v4_1_direction_updates_never_expand_event_bounds() -> None:
    agent = _agent()
    result = _result("未断裂", [0.0, 10.0])
    agent._transition_v4_1(result, result["model_output"])
    assert agent.event_bounds.interval == [20.0, 80.0]
    assert result["event_bounds_update"]["reason"] == "no_op"
    assert agent.candidate == [5.0, 95.0]


def test_v4_1_contradictory_direction_rejects_empty_event_bounds() -> None:
    agent = _agent()
    result = _result("未断裂", [70.0, 90.0])
    agent._transition_v4_1(result, result["model_output"])
    assert agent.event_bounds.interval == [20.0, 80.0]
    assert agent.event_bounds.unresolved_conflict is True
    assert result["event_bounds_update"]["conflict"] is True
    assert result["conflict_handled"] == "event_bounds_update_rejected"


def test_v4_1_local_event_can_resolve_prior_boundary_conflict() -> None:
    agent = _agent()
    conflict = _result("未断裂", [70.0, 90.0])
    agent._transition_v4_1(conflict, conflict["model_output"])
    confirmation = _result("发生断裂", [70.0, 90.0])
    agent._transition_v4_1(confirmation, confirmation["model_output"])
    assert agent.event_bounds.interval == [70.0, 80.0]
    assert agent.event_bounds.unresolved_conflict is False
    assert confirmation["event_bounds_update"]["conflict_resolved"] is True


def test_v4_1_unrelated_event_does_not_resolve_prior_boundary_conflict() -> None:
    agent = _agent()
    conflict = _result("未断裂", [70.0, 90.0])
    agent._transition_v4_1(conflict, conflict["model_output"])
    unrelated = _result("发生断裂", [35.0, 35.5])
    agent._transition_v4_1(unrelated, unrelated["model_output"])
    assert agent.event_bounds.interval == [35.0, 35.5]
    assert agent.event_bounds.unresolved_conflict is True
    assert agent.event_bounds.publishable(1.0) is False
    assert unrelated["event_bounds_update"]["conflict_resolved"] is False


def test_v4_1_all_boundary_conflicts_must_be_rechecked_before_publish() -> None:
    agent = _agent()
    first = _result("未断裂", [70.0, 90.0])
    second = _result("已断裂", [10.0, 15.0])
    agent._transition_v4_1(first, first["model_output"])
    agent._transition_v4_1(second, second["model_output"])
    first_recheck = _result("发生断裂", [70.0, 90.0])
    agent._transition_v4_1(first_recheck, first_recheck["model_output"])
    assert agent.event_bounds.unresolved_conflict is True
    assert agent.event_bounds.conflict_count == 1
    assert agent.event_bounds.publishable(20.0) is False


def test_v4_1_unknown_never_creates_search_direction() -> None:
    agent = _agent()
    agent._update_special_recheck = lambda _result: None
    result = _result("无法判断", [35.0, 42.0])
    agent._transition_v4_1(result, result["model_output"])
    assert agent.candidate == [20.0, 80.0]
    assert "v4_1_search_direction" not in result


def test_v4_1_special_case_is_projected_from_matching_evidence() -> None:
    agent = _agent()
    agent.visual_contract_version = "tensile-vlm/v4.1"
    agent.history = [
        {
            "result": {
                "model_output": {
                    "clip_state": "无法判断",
                    "fracture_mechanism": None,
                    "fracture_site": None,
                    "special_case": "未夹紧",
                }
            }
        }
    ]
    args = agent._build_final_args(
        {"status": "unrecognized", "unrecognized_reason": "not_clamped"}
    )
    assert args["special_case"] == "未夹紧"
