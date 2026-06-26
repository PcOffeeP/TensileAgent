from __future__ import annotations

import json
from pathlib import Path

from agent.schema import ModelOutput


FIXTURES = Path(__file__).parent / "fixtures"


def _load_json(name: str):
    with open(FIXTURES / name, encoding="utf-8") as f:
        return json.load(f)


def test_sample_model_outputs_are_valid():
    cases = _load_json("sample_model_outputs.json")
    for case in cases:
        output = ModelOutput(**case["model_output"])
        assert output.has_fracture == case["model_output"]["has_fracture"]


def test_sample_model_outputs_cover_video_anomaly_combinations():
    cases = _load_json("sample_model_outputs.json")
    assert len(cases) == 5
    descriptions = {case["description"] for case in cases}
    assert "video anomaly: fracture presence unknown" in descriptions
    assert "video anomaly: confirmed fracture but unreliable time" in descriptions

    by_description = {case["description"]: case["model_output"] for case in cases}

    unknown = by_description["video anomaly: fracture presence unknown"]
    assert unknown["has_fracture"] is None
    assert unknown["fracture_between"] is None
    assert unknown["type"] == "视频异常"
    assert unknown["location"] is None

    confirmed = by_description["video anomaly: confirmed fracture but unreliable time"]
    assert confirmed["has_fracture"] is True
    assert confirmed["fracture_between"] is None
    assert confirmed["type"] == "视频异常"
    assert confirmed["location"] is None


def test_sample_video_meta_has_required_fields():
    meta = _load_json("sample_video_meta.json")
    assert len(meta) >= 1
    for item in meta:
        assert "video_id" in item
        assert "fps" in item
        assert "total_frames" in item
        assert "duration" in item
        assert item["fps"] > 0
        assert item["total_frames"] > 0
