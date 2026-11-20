"""Regression tests for Stage 2: task config isolation, V2 rollback, B1–B5, and doctor."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from agent import doctor, runner
from agent.config_util import validate_tolerance_seconds
from agent.interaction import parse_user_intent
from agent.iterative_agent import IterativeAgent
from agent.llm import AgentLLMFactory, DeterministicPlanner
from agent.prompts import build_tensile_agent_user_context


def test_b1_prompt_reads_original_fps_and_displays_unknown_when_missing() -> None:
    ctx_original = build_tensile_agent_user_context(
        video_meta={"video_id": "v1", "duration": 10.0, "original_fps": 25.0},
        config={"agent": {"tolerance_seconds": 1.0, "max_rounds": 10}},
        current_round=1,
        candidate=[0.0, 10.0],
        history=[],
    )
    assert "FPS: 25.0" in ctx_original

    ctx_legacy = build_tensile_agent_user_context(
        video_meta={"video_id": "v1", "duration": 10.0, "fps": 30.0},
        config={"agent": {"tolerance_seconds": 1.0, "max_rounds": 10}},
        current_round=1,
        candidate=[0.0, 10.0],
        history=[],
    )
    assert "FPS: 30.0" in ctx_legacy

    ctx_unknown = build_tensile_agent_user_context(
        video_meta={"video_id": "v1", "duration": 10.0, "original_fps": None},
        config={"agent": {"tolerance_seconds": 1.0, "max_rounds": 10}},
        current_round=1,
        candidate=[0.0, 10.0],
        history=[],
    )
    assert "FPS: 未知" in ctx_unknown
    assert "FPS: 0.0" not in ctx_unknown


@pytest.mark.parametrize(
    "bad_tol",
    [0, -0.5, 1.5, 2.0, math.nan, math.inf, -math.inf, True, "1.0", None],
)
def test_b2_tolerance_validation_rejects_invalid_values(bad_tol: Any) -> None:
    with pytest.raises(ValueError, match="tolerance_seconds"):
        validate_tolerance_seconds(bad_tol)

    with pytest.raises(ValueError, match="tolerance_seconds"):
        DeterministicPlanner(tolerance_seconds=bad_tol)


def test_b2_runner_rejects_invalid_tolerance_before_calling_models(
    tmp_path: Path,
) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"fake")
    cfg = tmp_path / "bad_tol.yaml"
    cfg.write_text(
        "agent:\n  backend: deterministic\n  tolerance_seconds: 2.0\n",
        encoding="utf-8",
    )

    with patch("agent.runner.parse_user_intent") as mock_intent:
        result = runner.run_one(video, config_path=cfg)

    assert result["ok"] is False
    assert result["error"]["stage"] == "configuration"
    mock_intent.assert_not_called()


def test_b3_v2_invalid_index_persists_diagnostics_only_once(tmp_path: Path) -> None:
    from tests.test_iterative_agent import FakeClipBuilder, FakeInferenceClient, StaticLLM

    agent = IterativeAgent(
        llm_client=StaticLLM(
            [("sample_and_infer", {"sample_range": [0.0, 40.0], "task_mode": "analyze"})]
        ),
        video_meta={"video_id": "v_b3", "duration": 40.0, "video_path": "v_b3.mp4"},
        config={
            "agent": {"max_rounds": 1, "tolerance_seconds": 1.0, "temperature": 0.2},
            "backend": {"contract_version": "tensile-vlm/v2"},
        },
        clip_builder=FakeClipBuilder(),
        inference_client=FakeInferenceClient(
            [
                {
                    "has_fracture": True,
                    "fracture_between": [99, 100],
                    "type": "韧性断裂",
                    "location": "inside_gauge",
                    "confidence": 0.9,
                }
            ]
        ),
        work_dir=tmp_path,
    )

    persist_calls = 0
    original_persist = agent._persist_diagnostics

    def counting_persist(round_idx: int, diagnostics: Any) -> None:
        nonlocal persist_calls
        persist_calls += 1
        original_persist(round_idx, diagnostics)

    agent._persist_diagnostics = counting_persist  # type: ignore[method-assign]
    agent._execute_sample_and_infer(
        {"sample_range": [0.0, 40.0], "task_mode": "analyze"}, round_idx=0
    )

    assert persist_calls == 1


def test_b4_b5_task_config_passed_to_intent_and_defaults_local_0_2(
    tmp_path: Path,
) -> None:
    video = tmp_path / "demo.mp4"
    video.write_bytes(b"fake")
    cfg = tmp_path / "det.yaml"
    cfg.write_text(
        (
            "agent:\n"
            "  backend: deterministic\n"
            "  deterministic:\n"
            "    model: v4.1-interval-policy-v1\n"
            "backend:\n"
            "  contract_version: tensile-vlm/v4.1\n"
        ),
        encoding="utf-8",
    )

    captured_intent_config: dict[str, Any] = {}

    def fake_parse_intent(question: str | None, *, config: dict[str, Any] | None = None):
        if config is not None:
            captured_intent_config.update(config)
        return parse_user_intent(question, config=config)

    mock_agent = MagicMock()
    mock_agent.run.return_value = {
        "video_id": "demo",
        "status": "no_fracture",
        "confidence": None,
    }

    with (
        patch("agent.runner.parse_user_intent", side_effect=fake_parse_intent),
        patch(
            "agent.runner.build_video_meta",
            return_value={"video_id": "demo", "duration": 4.0, "video_path": str(video)},
        ),
        patch("agent.runner.create_llm_client", return_value=DeterministicPlanner()),
        patch("agent.runner.create_inference_client") as mock_inf_factory,
        patch("agent.runner.create_clip_builder", return_value=MagicMock()),
        patch("agent.iterative_agent.IterativeAgent", return_value=mock_agent),
    ):
        mock_inf_factory.return_value.preflight.return_value = {
            "contract_version": "tensile-vlm/v2"
        }
        result = runner.run_one(
            video,
            config_path=cfg,
            contract_version="tensile-vlm/v2",
        )

    assert result["ok"] is True
    assert captured_intent_config["agent"]["backend"] == "deterministic"
    assert captured_intent_config["agent"]["temperature"] == 0.2
    assert captured_intent_config["backend"]["contract_version"] == "tensile-vlm/v2"
    passed_inf_cfg = mock_inf_factory.call_args.args[0]
    assert passed_inf_cfg["backend"]["contract_version"] == "tensile-vlm/v2"


def test_b4_run_batch_propagates_contract_version(tmp_path: Path) -> None:
    video = tmp_path / "batch_v.mp4"
    video.write_bytes(b"fake")
    with patch("agent.runner.run_one", return_value={"ok": True}) as mock_run_one:
        results = runner.run_batch(
            [video],
            config_path="agent/config.yaml",
            contract_version="tensile-vlm/v2",
        )
    assert results == [{"ok": True}]
    assert mock_run_one.call_args.kwargs["contract_version"] == "tensile-vlm/v2"


def test_b4_factory_defaults_to_local_when_backend_omitted() -> None:
    with patch(
        "agent.llm.list_local_models",
        return_value={"ok": False, "models": [], "warning": "ollama down"},
    ) as mock_local:
        with pytest.raises(RuntimeError, match="ollama down"):
            AgentLLMFactory.create({})
    mock_local.assert_called_once()


def test_doctor_checks_remote_backend_without_probing_ollama(tmp_path: Path) -> None:
    cfg = tmp_path / "remote.yaml"
    cfg.write_text(
        (
            "agent:\n"
            "  backend: remote\n"
            "  remote:\n"
            "    model: qwen-max\n"
            "    base_url: https://example.com/v1\n"
            "    api_key: secret-key\n"
            "backend:\n"
            "  api_url: http://127.0.0.1:8001/v1\n"
            "  contract_version: tensile-vlm/v4.1\n"
        ),
        encoding="utf-8",
    )

    with (
        patch("agent.doctor.get_local_model_digest") as mock_ollama,
        patch("agent.doctor.requests.get", side_effect=RuntimeError("offline")),
    ):
        report = doctor.run_doctor(cfg)

    mock_ollama.assert_not_called()
    assert "ollama" not in report["checks"]
    assert report["checks"]["decision_backend"]["ok"] is True
    assert report["checks"]["decision_backend"]["backend"] == "remote"
