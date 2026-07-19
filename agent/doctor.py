"""Runtime readiness checks for the local TensileAgent MVP."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
from typing import Any

import requests

from agent.config_util import get_local_model_digest
from agent.contract import visual_contract_hash
from agent.runner import load_config


def run_doctor(config_path: str | Path = "agent/config.yaml") -> dict[str, Any]:
    config = load_config(config_path)
    local = config.get("agent", {}).get("local", {})
    backend = config.get("backend", {})
    checks: dict[str, dict[str, Any]] = {}
    for binary in ("ffmpeg", "ffprobe"):
        path = shutil.which(binary)
        checks[binary] = {"ok": path is not None, "path": path}

    model = str(local.get("model", ""))
    base_url = str(local.get("base_url", "http://localhost:11434/v1"))
    digest = get_local_model_digest(model, base_url)
    checks["ollama"] = {"ok": digest is not None, "model": model, "digest": digest}

    contract_url = f"{str(backend.get('api_url', 'http://localhost:8000/v1')).rstrip('/')}/tensile/contract"
    try:
        response = requests.get(contract_url, timeout=3)
        payload = response.json()
        contract_ok = (
            response.ok
            and payload.get("contract_version") == "tensile-vlm/v2"
            and payload.get("contract_hash") == visual_contract_hash()
        )
        checks["visual_service"] = {
            "ok": contract_ok,
            "url": contract_url,
            "contract_version": payload.get("contract_version"),
            "contract_hash": payload.get("contract_hash"),
        }
    except Exception as exc:  # noqa: BLE001
        checks["visual_service"] = {"ok": False, "url": contract_url, "error": str(exc)}

    runtime_dir = Path("data/08_runtime")
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=runtime_dir):
            pass
        checks["runtime_dir"] = {"ok": True, "path": str(runtime_dir)}
    except OSError as exc:
        checks["runtime_dir"] = {"ok": False, "path": str(runtime_dir), "error": str(exc)}

    return {"ok": all(check["ok"] for check in checks.values()), "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser(description="Check TensileAgent local runtime dependencies")
    parser.add_argument("--config", default="agent/config.yaml")
    args = parser.parse_args()
    import json

    result = run_doctor(args.config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
