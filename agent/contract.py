"""Load and fingerprint the pinned, self-contained visual contract."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CONTRACT_ROOT = Path(__file__).with_name("contracts")
CONTRACT_PATH = CONTRACT_ROOT / "tensile_vlm_v2.json"
CONTRACT_VERSION = "tensile-vlm/v2"
EXPECTED_CONTRACT_HASH = "d26adabe7d7236fc3c5f15dcaa3a7eb7cbeb681102be2c926fe5f4c4b0111102"
V4_1_CONTRACT_VERSION = "tensile-vlm/v4.1"
V4_1_EXPECTED_CONTRACT_HASH = (
    "3798f00cbec7a3cad3e50de66dd2b5bdeecca1a95ae74297cbd0d71e7ec438ab"
)
_CONTRACT_SPECS = {
    CONTRACT_VERSION: (CONTRACT_PATH, EXPECTED_CONTRACT_HASH),
    V4_1_CONTRACT_VERSION: (
        CONTRACT_ROOT / "tensile_vlm_v4_1.json",
        V4_1_EXPECTED_CONTRACT_HASH,
    ),
}


def canonical_contract_bytes(contract: dict[str, Any]) -> bytes:
    """Serialize contract content deterministically, excluding its own hash."""
    normalized = dict(contract)
    normalized.pop("contract_hash", None)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


@lru_cache(maxsize=2)
def load_visual_contract(
    contract_version: str = CONTRACT_VERSION,
) -> dict[str, Any]:
    try:
        path, expected_hash = _CONTRACT_SPECS[contract_version]
    except KeyError as exc:
        raise RuntimeError(f"unsupported visual contract: {contract_version}") from exc
    raw = path.read_text(encoding="utf-8")
    contract = json.loads(raw)
    if contract_version == V4_1_CONTRACT_VERSION:
        required = {
            "contract_version",
            "model_output_fields",
            "contract_hash",
            "model_output_schema",
            "clip_states",
            "fracture_mechanisms",
            "fracture_sites",
            "special_cases",
            "analysis",
            "evidence",
            "video",
            "search_semantics",
            "validation_rules",
        }
        missing = required - contract.keys()
        if missing:
            raise RuntimeError(f"visual contract missing fields: {sorted(missing)}")
        if contract["model_output_fields"] != [
            "clip_state",
            "fracture_mechanism",
            "fracture_site",
            "special_case",
        ]:
            raise RuntimeError("V4.1 visual contract field order drifted")
        if contract.get("contract_version") != contract_version:
            raise RuntimeError("V4.1 visual contract version drifted")
        analysis = contract.get("analysis")
        evidence = contract.get("evidence")
        if not isinstance(analysis, dict) or not all(
            isinstance(analysis.get(key), str) and analysis[key].strip()
            for key in ("system_prompt", "user_prompt", "retry_prompt")
        ):
            raise RuntimeError("V4.1 visual contract analysis prompts must be non-empty")
        if not isinstance(evidence, dict) or not all(
            isinstance(evidence.get(key), str) and evidence[key].strip()
            for key in ("system_prompt", "user_prompt")
        ):
            raise RuntimeError("V4.1 visual contract evidence prompts must be non-empty")
        actual_hash = hashlib.sha256(canonical_contract_bytes(contract)).hexdigest()
        if contract.get("contract_hash") != actual_hash or actual_hash != expected_hash:
            raise RuntimeError("V4.1 visual contract hash mismatch")
        return contract
    required = {
        "contract_version",
        "model_output_fields",
        "contract_hash",
        "model_output_schema",
        "fracture_types",
        "other_types",
        "anomaly_types",
        "locations",
        "analysis",
        "evidence",
        "video",
        "validation_rules",
    }
    missing = required - contract.keys()
    if missing:
        raise RuntimeError(f"visual contract missing fields: {sorted(missing)}")
    if contract["model_output_fields"] != [
        "has_fracture",
        "fracture_between",
        "type",
        "location",
    ]:
        raise RuntimeError("visual contract model_output_fields must be the trained four-field order")
    if contract["contract_version"] != CONTRACT_VERSION:
        raise RuntimeError(f"unsupported visual contract: {contract['contract_version']}")
    if contract["fracture_types"] != [
        "韧性断裂",
        "脆性断裂",
        "界面脱粘",
        "齐根断裂",
        "爆炸性断裂",
        "半脆半韧断裂",
        "界面脱粘、齐根断裂",
        "脆性断裂、齐根断裂",
    ]:
        raise RuntimeError("visual contract fracture_types do not match the production enum")
    if contract["other_types"] != ["未断裂", "未夹紧"]:
        raise RuntimeError("visual contract other_types do not match the production enum")
    if contract["anomaly_types"] != ["视频异常"]:
        raise RuntimeError("visual contract anomaly_types must contain only 视频异常")
    if contract["locations"] != ["inside_gauge", "outside_gauge"]:
        raise RuntimeError("visual contract locations do not match the production enum")
    analysis = contract.get("analysis")
    evidence = contract.get("evidence")
    if not isinstance(analysis, dict) or not all(
        isinstance(analysis.get(key), str) and analysis[key].strip()
        for key in ("system_prompt", "user_prompt", "retry_prompt")
    ):
        raise RuntimeError("visual contract analysis prompts must be non-empty")
    if not isinstance(evidence, dict) or not all(
        isinstance(evidence.get(key), str) and evidence[key].strip()
        for key in ("system_prompt", "user_prompt")
    ):
        raise RuntimeError("visual contract evidence prompts must be non-empty")
    actual_hash = hashlib.sha256(canonical_contract_bytes(contract)).hexdigest()
    if contract["contract_hash"] != actual_hash:
        raise RuntimeError(
            f"visual contract hash mismatch: artifact={contract['contract_hash']} canonical={actual_hash}"
        )
    if actual_hash != expected_hash:
        raise RuntimeError(
            f"visual contract fixed hash mismatch: expected={expected_hash} actual={actual_hash}"
        )
    return contract


def visual_contract_hash(contract_version: str = CONTRACT_VERSION) -> str:
    return str(load_visual_contract(contract_version)["contract_hash"])
