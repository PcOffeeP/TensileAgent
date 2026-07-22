import hashlib
import json
from pathlib import Path

import pytest


CONTRACT_PATH = (
    Path(__file__).parents[1] / "agent" / "contracts" / "tensile_vlm_v3.json"
)
EXPECTED_HASH = "3f9f8217774cb4947fc4e19e41a5fe14b8a5ea30c8e84ed4f664abddd9de04f0"
EXPECTED_FIELDS = [
    "clip_state",
    "fracture_mechanism",
    "root_break",
    "location",
    "special_case",
]


def _load_contract(path: Path = CONTRACT_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_hash(contract: dict) -> str:
    normalized = dict(contract)
    normalized.pop("contract_hash", None)
    payload = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_v3_target_contract_is_fixed_without_switching_runtime():
    contract = _load_contract()
    assert contract["contract_version"] == "tensile-vlm/v3"
    assert contract["contract_hash"] == _canonical_hash(contract) == EXPECTED_HASH
    assert contract["model_output_fields"] == EXPECTED_FIELDS
    assert contract["search_semantics"]["direction_field"] == "clip_state"
    assert contract["search_semantics"]["无法判断"] == "no_directional_evidence"


def test_v3_schema_requires_exact_hierarchical_fields():
    schema = _load_contract()["model_output_schema"]
    assert schema["additionalProperties"] is False
    assert schema["required"] == EXPECTED_FIELDS
    assert set(schema["properties"]) == set(EXPECTED_FIELDS)
    assert schema["properties"]["root_break"]["type"] == ["boolean", "null"]


def test_v3_analysis_prompt_does_not_request_v2_frame_indexes():
    contract = _load_contract()
    prompt = "\n".join(
        contract["analysis"][key]
        for key in ("system_prompt", "user_prompt", "retry_prompt")
    )
    assert "clip_state" in prompt
    assert "fracture_between" not in prompt
    assert "has_fracture" not in prompt


def test_v3_authoritative_sibling_contract_matches_when_available():
    sibling = (
        CONTRACT_PATH.parents[3]
        / "mVllm_2"
        / "pipeline"
        / "contracts"
        / CONTRACT_PATH.name
    )
    if not sibling.exists():
        pytest.skip("mVllm_2 sibling checkout is not available")
    assert _load_contract(sibling) == _load_contract()
