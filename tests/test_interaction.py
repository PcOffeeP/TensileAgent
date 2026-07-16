import pytest

from agent.interaction import parse_user_intent, project_result


def test_natural_fracture_question_requests_only_decision():
    intent = parse_user_intent("这个拉伸视频断了吗？")
    assert intent.action == "analyze_video"
    assert intent.requested_fields == ["has_fracture"]
    assert intent.wants_evidence is False


def test_natural_time_and_reason_question_requests_evidence():
    intent = parse_user_intent("什么时候断的，为什么这样判断？")
    assert intent.requested_fields == ["time_range", "visual_evidence"]
    assert intent.wants_evidence is True


def test_unrelated_question_is_rejected_before_visual_inference():
    intent = parse_user_intent("明天北京天气怎么样？")
    assert intent.action == "unsupported"


def test_projection_only_returns_requested_fields():
    intent = parse_user_intent("断了吗？")
    response = project_result(
        {
            "status": "fracture",
            "time_range": [1.0, 1.5],
            "fracture_type": "韧性断裂",
            "location": "inside_gauge",
            "confidence": {"overall": None, "evidence_level": "high"},
        },
        intent,
    )
    assert response["status"] == "answered"
    assert response["answer"] == {"has_fracture": True}


def test_common_colloquial_time_question_is_recognized():
    intent = parse_user_intent("几秒断的？")
    assert intent.action == "analyze_video"
    assert intent.requested_fields == ["time_range"]


def test_common_location_question_requests_location():
    intent = parse_user_intent("断裂发生在什么地方？")
    assert intent.requested_fields == ["has_fracture", "location"]


@pytest.mark.parametrize(
    ("question", "field"),
    [
        ("试样断列了吗？", "has_fracture"),
        ("哪一秒发生段裂？", "time_range"),
        ("Where did it fracture?", "location"),
        ("What type of fracture is this?", "type"),
    ],
)
def test_bilingual_and_common_typo_intents(question, field):
    assert field in parse_user_intent(question).requested_fields
