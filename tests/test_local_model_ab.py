from scripts.run_local_model_ab import (
    CRITICAL_IDS,
    SCENARIOS,
    meets_acceptance,
    validate_tool,
)


def test_ab_manifest_has_twenty_unique_scenarios_and_five_critical_repeats():
    ids = [item["id"] for item in SCENARIOS]
    assert len(ids) == 20
    assert len(set(ids)) == 20
    assert len(CRITICAL_IDS) == 5
    assert CRITICAL_IDS <= set(ids)
    assert {"prompt_injection", "unrelated_text"} <= set(ids)


def test_ab_tool_validation_rejects_unknown_and_invalid_arguments():
    assert validate_tool(
        "sample_and_infer", {"sample_range": [0, 40], "task_mode": "analyze"}
    )
    assert not validate_tool("upload_video", {})
    assert not validate_tool(
        "terminate",
        {
            "status": "unrecognized",
            "fracture_type": "None",
            "unrecognized_reason": "video_anomaly",
        },
    )


def test_ab_acceptance_rejects_legal_but_wrong_tool_selection():
    summary = {
        "structure_rate": 1.0,
        "schema_rate": 1.0,
        "expected_tool_rate": 0.95,
        "hallucinated_tools": 0,
    }
    assert not meets_acceptance(summary)
