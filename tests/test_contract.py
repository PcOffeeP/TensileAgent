import json
from pathlib import Path

import pytest

from agent.contract import CONTRACT_PATH, load_visual_contract, visual_contract_hash
from agent.inference import _validate_preprocessing_meta
from agent.prompts import PRODUCTION_USER_PROMPT, build_user_prompt
from agent.schema import ToolSampleAndInfer, ToolTerminate, VisualEvidence


def _deployment_manifest() -> dict:
    return {
        "model_version": "minicpm-v-4.5",
        "transformers_version": "4.test",
        "llamafactory_version": "test-rev",
        "base_model_version": "base-test",
        "artifact_version": "adapter-test",
        "config_fingerprint": "sha256:test",
        "runtime_device": "cpu",
        "runtime_dtype": "float32",
        "contract_version": "tensile-vlm/v1",
        "prompt_contract_hash": visual_contract_hash(),
    }


def _preprocessing() -> dict:
    return {
        "request_id": "request-1",
        "processor_version": "minicpmv4.5/0.1",
        "max_frames": 8,
        "frames": [{"index": i, "timestamp": float(i)} for i in range(8)],
        "deployment_manifest": _deployment_manifest(),
    }


def test_contract_is_four_field_and_fixed_prompt():
    contract = load_visual_contract()
    assert contract["model_output_fields"] == [
        "has_fracture", "fracture_between", "type", "location"
    ]
    assert build_user_prompt([0.0, 1.0]) == build_user_prompt([10.0, 20.0]) == PRODUCTION_USER_PROMPT


def test_runtime_accepts_matching_contract_and_rejects_drift():
    metadata = _preprocessing()
    assert _validate_preprocessing_meta(metadata) is None
    metadata["deployment_manifest"]["prompt_contract_hash"] = "0" * 64
    assert _validate_preprocessing_meta(metadata) == "prompt_contract_hash_mismatch"


def test_tool_schemas_do_not_expose_free_prompt_or_confidence():
    assert "prompt" not in ToolSampleAndInfer.model_json_schema()["properties"]
    assert "confidence" not in ToolTerminate.model_json_schema()["properties"]


def test_visual_evidence_reference_keeps_frame_trace():
    evidence = VisualEvidence(
        status="available",
        summary="试样逐渐伸长后发生分离。",
        references=[{
            "round": 1,
            "sample_range": [2.0, 4.0],
            "frame_timestamps": [2.0, 2.5, 3.0, 3.5, 4.0],
            "clip_hash": "abc",
            "request_id": "request-1",
        }],
    )
    assert evidence.references[0].frame_timestamps[-1] == 4.0


def test_sibling_authoritative_contract_matches_when_available():
    sibling = CONTRACT_PATH.parents[3] / "mVllm_2" / "pipeline" / "contracts" / CONTRACT_PATH.name
    if not sibling.exists():
        pytest.skip("mVllm_2 sibling checkout is not available")
    assert json.loads(sibling.read_text(encoding="utf-8")) == load_visual_contract()

