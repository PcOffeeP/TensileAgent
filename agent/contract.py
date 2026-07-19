"""Load and fingerprint the pinned, self-contained visual contract."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CONTRACT_PATH = Path(__file__).with_name("contracts") / "tensile_vlm_v2.json"
CONTRACT_VERSION = "tensile-vlm/v2"


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


@lru_cache(maxsize=1)
def load_visual_contract() -> dict[str, Any]:
    raw = CONTRACT_PATH.read_text(encoding="utf-8")
    contract = json.loads(raw)
    required = {
        "contract_version",
        "model_output_fields",
        "contract_hash",
        "model_output_schema",
        "fracture_types",
        "other_types",
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
    actual_hash = hashlib.sha256(canonical_contract_bytes(contract)).hexdigest()
    if contract["contract_hash"] != actual_hash:
        raise RuntimeError(
            f"visual contract hash mismatch: artifact={contract['contract_hash']} canonical={actual_hash}"
        )
    return contract


def visual_contract_hash() -> str:
    return str(load_visual_contract()["contract_hash"])
