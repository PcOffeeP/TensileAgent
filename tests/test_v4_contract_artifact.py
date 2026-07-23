import hashlib
import json
from pathlib import Path

import pytest


CONTRACT_PATH = (
    Path(__file__).parents[1] / "agent" / "contracts" / "tensile_vlm_v4.json"
)
EXPECTED_HASH = "d25df900c0c5e0013e20d40fb01202939b465b3fb4ede4fdd8268d983c2c6481"
EXPECTED_FIELDS = [
    "clip_state",
    "fracture_mechanism",
    "fracture_site",
    "special_case",
]


def _load_contract(path: Path = CONTRACT_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _canonical_hash(contract: dict) -> str:
    normalized = dict(contract)
    normalized.pop("contract_hash", None)
    payload = json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def test_v4_target_contract_is_fixed_without_switching_runtime():
    contract = _load_contract()
    assert contract["contract_version"] == "tensile-vlm/v4"
    assert contract["contract_hash"] == _canonical_hash(contract) == EXPECTED_HASH
    assert contract["model_output_fields"] == EXPECTED_FIELDS
    assert contract["search_semantics"]["direction_field"] == "clip_state"


def test_v4_schema_replaces_overlapping_root_and_location_fields():
    contract = _load_contract()
    schema = contract["model_output_schema"]
    assert schema["required"] == EXPECTED_FIELDS
    assert set(schema["properties"]) == set(EXPECTED_FIELDS)
    assert schema["properties"]["fracture_site"]["enum"] == [
        "inside_gauge",
        "outside_gauge_non_root",
        "grip_root",
        None,
    ]
    assert "root_break" not in schema["properties"]
    assert "location" not in schema["properties"]


def test_v4_severity_projection_is_deterministic_agent_owned_semantics():
    assert _load_contract()["fracture_site_severity"] == {
        "inside_gauge": "acceptable",
        "outside_gauge_non_root": "unfavorable",
        "grip_root": "severe_unfavorable",
        "null": "unavailable",
    }


def test_v4_authoritative_sibling_contract_matches_when_available():
    sibling = (
        CONTRACT_PATH.parents[3]
        / "mVllm_2"
        / "pipeline"
        / "contracts"
        / CONTRACT_PATH.name
    )
    if not sibling.exists():
        pytest.skip("mVllm_2 sibling checkout is not available")
    assert sibling.read_bytes() == CONTRACT_PATH.read_bytes()
