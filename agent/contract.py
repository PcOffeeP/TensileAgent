"""Load and fingerprint the pinned MiniCPM visual contract."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any


CONTRACT_PATH = Path(__file__).with_name("contracts") / "tensile_vlm_v1.json"


@lru_cache(maxsize=1)
def load_visual_contract() -> dict[str, Any]:
    raw = CONTRACT_PATH.read_text(encoding="utf-8")
    contract = json.loads(raw)
    required = {
        "contract_version",
        "model_output_fields",
        "system_prompt",
        "user_prompt",
        "evidence_system_prompt",
        "evidence_user_prompt",
        "generation",
        "video",
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
    return contract


def visual_contract_hash() -> str:
    return hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()
