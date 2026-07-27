from __future__ import annotations

from agent.contract import (
    V4_1_CONTRACT_VERSION,
    V4_1_EXPECTED_CONTRACT_HASH,
    load_visual_contract,
    visual_contract_hash,
)
from agent.v4_1_parser import V4_1ResultParser
from agent.http_vlm_stub import create_app
from fastapi.testclient import TestClient


def test_v4_1_runtime_contract_loads_promoted_prompt() -> None:
    contract = load_visual_contract(V4_1_CONTRACT_VERSION)
    assert contract["contract_hash"] == V4_1_EXPECTED_CONTRACT_HASH
    assert visual_contract_hash(V4_1_CONTRACT_VERSION) == V4_1_EXPECTED_CONTRACT_HASH
    assert "按时间顺序判断试样连续性" in contract["analysis"]["user_prompt"]


def test_v4_1_runtime_parser_accepts_exact_fields_and_rejects_synonyms() -> None:
    valid = V4_1ResultParser.parse(
        '{"clip_state":"已断裂","fracture_mechanism":"界面脱粘",'
        '"fracture_site":"grip_root","special_case":null}'
    )
    assert valid.ok is True
    invalid = V4_1ResultParser.parse(
        '{"clip_state":"已断裂","fracture_mechanism":"沿界面断裂",'
        '"fracture_site":"grip_root","special_case":null}'
    )
    assert invalid.ok is False


def test_v4_1_http_stub_is_version_pinned() -> None:
    client = TestClient(create_app(contract_version=V4_1_CONTRACT_VERSION))
    payload = client.get("/v1/tensile/contract").json()
    assert payload["contract_version"] == V4_1_CONTRACT_VERSION
    assert payload["contract_hash"] == V4_1_EXPECTED_CONTRACT_HASH
