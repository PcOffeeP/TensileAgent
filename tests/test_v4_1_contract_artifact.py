import hashlib
import json
from pathlib import Path

import pytest


PATH = Path(__file__).parents[1] / "agent/contracts/tensile_vlm_v4_1.json"
EXPECTED_HASH = "47e393007ff1677c8b60a47d6d86f8181d7b1388a238d79469a3046bc045b937"


def test_v4_1_target_contract_is_fixed_without_switching_runtime():
    contract = json.loads(PATH.read_text())
    normalized = dict(contract)
    normalized.pop("contract_hash")
    actual = hashlib.sha256(
        json.dumps(
            normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    assert contract["contract_version"] == "tensile-vlm/v4.1"
    assert contract["contract_hash"] == actual == EXPECTED_HASH
    assert "临界未断裂" in contract["clip_states"]


def test_v4_1_incipient_summary_is_prospective_not_final():
    contract = json.loads(PATH.read_text())
    semantics = contract["search_semantics"]
    assert semantics["临界未断裂"].endswith("visible_precursors")
    assert semantics["summary_evidence_phase"]["临界未断裂"] == "prospective"
    assert contract["validation_rules"]["未断裂"].startswith(
        "fracture_mechanism"
    )


def test_v4_1_authoritative_sibling_contract_is_byte_identical():
    sibling = (
        PATH.parents[3]
        / "mVllm_2"
        / "pipeline/contracts/tensile_vlm_v4_1.json"
    )
    if not sibling.exists():
        pytest.skip("mVllm_2 sibling checkout is not available")
    assert sibling.read_bytes() == PATH.read_bytes()
