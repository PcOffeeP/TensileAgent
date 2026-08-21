"""Runtime readiness checks for the local TensileAgent MVP."""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
from typing import Any

import requests

from agent.config_util import get_inference_api_key, get_local_model_digest
from agent.contract import CONTRACT_VERSION, visual_contract_hash
from agent.runner import load_config


def run_doctor(config_path: str | Path = "agent/config.yaml") -> dict[str, Any]:
    config = load_config(config_path)
    local = config.get("agent", {}).get("local", {})
    backend = config.get("backend", {})
    contract_version = str(backend.get("contract_version") or CONTRACT_VERSION)
    checks: dict[str, dict[str, Any]] = {}
    for binary in ("ffmpeg", "ffprobe"):
        path = shutil.which(binary)
        checks[binary] = {"ok": path is not None, "path": path}

    decision_backend = str(config.get("agent", {}).get("backend", "local"))
    if decision_backend == "deterministic":
        planner = config.get("agent", {}).get("deterministic", {})
        checks["decision_backend"] = {
            "ok": planner.get("model")
            in {"v4.1-interval-policy-v1", "v2-interval-policy-v1"},
            "backend": decision_backend,
            "model": planner.get("model"),
        }
    else:
        model = str(local.get("model", ""))
        base_url = str(local.get("base_url", "http://localhost:11434/v1"))
        digest = get_local_model_digest(model, base_url)
        checks["ollama"] = {"ok": digest is not None, "model": model, "digest": digest}

    contract_url = f"{str(backend.get('api_url', 'http://localhost:8000/v1')).rstrip('/')}/tensile/contract"
    inference_api_key = get_inference_api_key()
    headers = (
        {"Authorization": f"Bearer {inference_api_key}"} if inference_api_key else {}
    )
    try:
        response = requests.get(contract_url, headers=headers, timeout=3)
        payload = response.json()
        contract_ok = (
            response.ok
            and payload.get("contract_version") == contract_version
            and payload.get("contract_hash") == visual_contract_hash(contract_version)
        )
        checks["visual_service"] = {
            "ok": contract_ok,
            "url": contract_url,
            "auth_configured": inference_api_key is not None,
            "contract_version": payload.get("contract_version"),
            "contract_hash": payload.get("contract_hash"),
        }
    except Exception as exc:  # noqa: BLE001
        checks["visual_service"] = {
            "ok": False,
            "url": contract_url,
            "auth_configured": inference_api_key is not None,
            "error": str(exc),
        }

    runtime_dir = Path("data/08_runtime")
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=runtime_dir):
            pass
        checks["runtime_dir"] = {"ok": True, "path": str(runtime_dir)}
    except OSError as exc:
        checks["runtime_dir"] = {
            "ok": False,
            "path": str(runtime_dir),
            "error": str(exc),
        }

    return {"ok": all(check["ok"] for check in checks.values()), "checks": checks}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check TensileAgent local runtime dependencies"
    )
    parser.add_argument("--config", default="agent/config.yaml")
    args = parser.parse_args()
    import json

    result = run_doctor(args.config)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
