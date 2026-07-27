"""Protocol-compatible HTTP visual backend for local MVP acceptance."""

from __future__ import annotations

import argparse
import base64
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from agent.contract import (
    CONTRACT_VERSION,
    V4_1_CONTRACT_VERSION,
    load_visual_contract,
    visual_contract_hash,
)


def _deployment_manifest(
    contract_version: str = CONTRACT_VERSION,
    *,
    drift: bool = False,
) -> dict[str, str]:
    contract = load_visual_contract(contract_version)
    return {
        "model_version": "tensile-http-stub/1",
        "adapter_version": "stub-adapter-drifted" if drift else "stub-adapter/1",
        "base_model_version": "stub-base/1",
        "processor_version": "stub-processor/1",
        "llamafactory_version": "stub-llamafactory/1",
        "transformers_version": "stub-transformers/1",
        "config_fingerprint": "sha256:stub-config-v1",
        "runtime_device": "cpu",
        "runtime_dtype": "float32",
        "contract_version": str(contract["contract_version"]),
        "contract_hash": visual_contract_hash(contract_version),
    }


class StubConfig(BaseModel):
    """Mutable scenario selection used by tests and the standalone server."""

    model_config = ConfigDict(extra="forbid")

    scenario: str = "fracture"


def _scenario_output(
    scenario: str,
    contract_version: str = CONTRACT_VERSION,
) -> str:
    if contract_version == V4_1_CONTRACT_VERSION:
        outputs = {
            "fracture": (
                '{"clip_state":"发生断裂","fracture_mechanism":"韧性断裂",'
                '"fracture_site":"inside_gauge","special_case":null}'
            ),
            "partial": (
                '{"clip_state":"发生断裂","fracture_mechanism":null,'
                '"fracture_site":null,"special_case":null}'
            ),
            "no-fracture": (
                '{"clip_state":"未断裂","fracture_mechanism":null,'
                '"fracture_site":null,"special_case":null}'
            ),
            "not-clamped": (
                '{"clip_state":"无法判断","fracture_mechanism":null,'
                '"fracture_site":null,"special_case":"未夹紧"}'
            ),
            "unknown": (
                '{"clip_state":"无法判断","fracture_mechanism":null,'
                '"fracture_site":null,"special_case":"视频异常"}'
            ),
            "invalid": '{"clip_state":"发生断裂","unexpected":1}',
            "drift": (
                '{"clip_state":"发生断裂","fracture_mechanism":"韧性断裂",'
                '"fracture_site":"inside_gauge","special_case":null}'
            ),
        }
        return outputs.get(scenario, outputs["fracture"])
    outputs = {
        "fracture": (
            '{"has_fracture":true,"fracture_between":[2,3],'
            '"type":"韧性断裂","location":"inside_gauge"}'
        ),
        "partial": (
            '{"has_fracture":true,"fracture_between":null,'
            '"type":null,"location":null}'
        ),
        "no-fracture": (
            '{"has_fracture":false,"fracture_between":null,'
            '"type":"未断裂","location":null}'
        ),
        "not-clamped": (
            '{"has_fracture":false,"fracture_between":null,'
            '"type":"未夹紧","location":null}'
        ),
        "unknown": (
            '{"has_fracture":null,"fracture_between":null,'
            '"type":null,"location":null}'
        ),
        "invalid": '{"has_fracture":true,"unexpected":1}',
        "drift": (
            '{"has_fracture":true,"fracture_between":[2,3],'
            '"type":"韧性断裂","location":"inside_gauge"}'
        ),
    }
    return outputs.get(scenario, outputs["fracture"])


def _extract_video_and_manifest(payload: dict[str, Any]) -> tuple[bytes, list[dict[str, Any]]]:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages must be an array")
    data_url: str | None = None
    for message in messages:
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") == "video_url":
                data_url = (item.get("video_url") or {}).get("url")
    if not isinstance(data_url, str) or not data_url.startswith("data:video/mp4;base64,"):
        raise HTTPException(status_code=400, detail="a Base64 video/mp4 is required")
    try:
        video = base64.b64decode(data_url.split(",", 1)[1], validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="invalid Base64 video") from exc
    if len(video) < 8 or video[4:8] != b"ftyp":
        raise HTTPException(status_code=400, detail="invalid MP4 payload")
    extra = payload.get("preprocessing") or {}
    manifest = extra.get("temp_video_manifest") if isinstance(extra, dict) else None
    return video, manifest if isinstance(manifest, list) else []


def _frame_table(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if manifest:
        indexes = [round(i * (len(manifest) - 1) / 7) for i in range(8)] if len(manifest) > 8 else range(len(manifest))
        selected = [manifest[index] for index in indexes]
        return [
            {"index": index, "timestamp": float(item.get("clip_timestamp", index))}
            for index, item in enumerate(selected)
        ]
    return [{"index": index, "timestamp": float(index)} for index in range(8)]


def create_app(
    scenario: str = "fracture",
    contract_version: str = CONTRACT_VERSION,
) -> FastAPI:
    """Create a deterministic stub app for one named failure/success scenario."""
    contract = load_visual_contract(contract_version)
    app = FastAPI(title="Tensile VLM HTTP Stub")
    app.state.stub_config = StubConfig(scenario=scenario)

    @app.get("/v1/tensile/contract")
    def get_contract() -> dict[str, Any]:
        return {
            "contract_version": contract["contract_version"],
            "contract_hash": visual_contract_hash(contract_version),
            "deployment_manifest": _deployment_manifest(contract_version),
            "capabilities": {"analysis": True, "evidence": True},
        }

    @app.post("/v1/chat/completions")
    def chat_completions(payload: dict[str, Any]) -> dict[str, Any]:
        selected_scenario = app.state.stub_config.scenario
        if selected_scenario == "transport-failure":
            raise HTTPException(status_code=503, detail="simulated transport failure")
        _, manifest = _extract_video_and_manifest(payload)
        frames = _frame_table(manifest)
        messages = payload.get("messages") or []
        system_text = str(messages[0].get("content", "")) if messages else ""
        is_evidence = "视频观察助手" in system_text
        content = (
            "试样逐渐伸长并变细，随后可见连续性中断。"
            if is_evidence
            else _scenario_output(selected_scenario, contract_version)
        )
        request_id = f"stub-{uuid.uuid4()}"
        return {
            "id": request_id,
            "object": "chat.completion",
            "created": 0,
            "model": payload.get("model", "tensile-http-stub"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "preprocessing": {
                "request_id": request_id,
                "processor_version": "stub-processor/1",
                "max_frames": 8,
                "frames": frames,
                "deployment_manifest": _deployment_manifest(
                    contract_version,
                    drift=selected_scenario == "drift",
                ),
            },
        }

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a version-pinned Tensile VLM HTTP stub")
    parser.add_argument(
        "--scenario",
        choices=[
            "fracture", "partial", "no-fracture", "not-clamped",
            "unknown", "invalid", "drift", "transport-failure",
        ],
        default="fracture",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--contract-version",
        choices=[CONTRACT_VERSION, V4_1_CONTRACT_VERSION],
        default=CONTRACT_VERSION,
    )
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(
        create_app(args.scenario, args.contract_version),
        host=args.host,
        port=args.port,
    )


if __name__ == "__main__":
    main()
