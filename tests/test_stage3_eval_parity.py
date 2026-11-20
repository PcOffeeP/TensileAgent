"""Stage 3 offline prep tests: planner parity, retry_count trace, A/B/C gate, delivery gate."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent.inference import InferenceResult
from agent.iterative_agent import IterativeAgent
from agent.llm import DeterministicPlanner, LocalClient, RemoteAPIClient
from agent.llm_trace import TransportTraceRecorder
from agent.sampling import ClipBuildResult
from agent.strategy_ab import map_single_call
from scripts.generate_delivery_bundle import REQUIRED_DELIVERY_CHECKS, _load_delivery_gate
from scripts.run_strategy_ab import _visual_round
from tests.test_v4_1_coverage_scheduler import RecordingClipBuilder, V41InferenceClient, _output


def test_deterministic_planner_sees_program_scheduled_rounds_with_stable_evidence_index() -> None:
    """When coverage hits a positive round, DeterministicPlanner sees its real evidence_index."""
    outputs = [
        _output("未断裂"),          # evidence_index 0: [0, 40] (planner) -> enters COVERAGE
        _output("未断裂"),          # evidence_index 1: [0, 10] (program/scheduler)
        _output("发生断裂"),        # evidence_index 2: [7.5, 17.5] (program/scheduler) -> exits COVERAGE
        _output("发生断裂"),        # evidence_index 3: narrowed local window
        _output("发生断裂"),        # evidence_index 4: narrowed local window
        _output("发生断裂"),        # evidence_index 5: narrowed local window
        _output("发生断裂"),        # evidence_index 6: narrowed local window
        _output("发生断裂"),        # evidence_index 7: narrowed local window
    ]
    planner = DeterministicPlanner(model="v4.1-interval-policy-v1", tolerance_seconds=1.0)
    clip_builder = RecordingClipBuilder()
    agent = IterativeAgent(
        llm_client=planner,
        video_meta={"video_id": "v_parity", "duration": 40.0, "video_path": "v.mp4"},
        config={
            "agent": {"max_rounds": 10, "tolerance_seconds": 1.0, "temperature": 0.2},
            "backend": {"contract_version": "tensile-vlm/v4.1"},
        },
        clip_builder=clip_builder,
        inference_client=V41InferenceClient(outputs),
    )

    result = agent.run()

    assert result["status"] == "fracture"
    assert result["time_range"] is not None
    assert result["time_range"][1] - result["time_range"][0] <= 1.0 + 1e-9
    # Verify planner cited real history index 2 (from program/scheduler), not a shifted index.
    positive_indices = [
        idx
        for idx, entry in enumerate(agent.history)
        if (entry["result"].get("model_output") or {}).get("clip_state") == "发生断裂"
    ]
    assert 2 in positive_indices


def test_decision_trace_records_actual_retry_count_on_success_and_failure(
    tmp_path: Path,
) -> None:
    recorder = TransportTraceRecorder(
        tmp_path,
        "task-retry",
        {"backend": "local", "model": "test-model"},
    )
    client = LocalClient(
        model="test-model",
        base_url="http://localhost:11434/v1",
        trace_recorder=recorder,
    )

    ok_response = MagicMock()
    ok_response.model_dump.return_value = {"choices": []}

    attempts = {"n": 0}

    def flaky_create(**kwargs: object) -> object:
        del kwargs
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise TimeoutError("transient timeout")
        return ok_response

    with (
        patch.object(client.client.chat.completions, "create", side_effect=flaky_create),
        patch("agent.llm.time.sleep"),
    ):
        client.chat_with_tools(messages=[{"role": "user", "content": "hi"}], tools=[])

    trace_1 = json.loads((tmp_path / "task-retry" / "round-0001.json").read_text("utf-8"))
    assert trace_1["retry_count"] == 1
    assert trace_1["error"] is None

    # Exhaust retries on remote client too -> retry_count == 2
    remote_recorder = TransportTraceRecorder(
        tmp_path,
        "task-retry-fail",
        {"backend": "remote", "model": "test-remote"},
    )
    remote = RemoteAPIClient(
        model="test-remote",
        api_key="sk-test",
        base_url="https://example.com/v1",
        trace_recorder=remote_recorder,
    )
    with (
        patch.object(
            remote.client.chat.completions,
            "create",
            side_effect=TimeoutError("still down"),
        ),
        patch("agent.llm.time.sleep"),
        pytest.raises(TimeoutError),
    ):
        remote.chat_with_tools(messages=[{"role": "user", "content": "hi"}], tools=[])

    trace_2 = json.loads(
        (tmp_path / "task-retry-fail" / "round-0001.json").read_text("utf-8")
    )
    assert trace_2["retry_count"] == 2
    assert trace_2["error"]["type"] == "TimeoutError"


def test_strategy_ab_visual_round_rejects_missing_preprocessing_metadata(
    tmp_path: Path,
) -> None:
    class NoMetadataClient:
        deployment_snapshot = V41InferenceClient.deployment_snapshot

        def infer(self, clip: ClipBuildResult) -> InferenceResult:
            del clip
            return InferenceResult(
                ok=True,
                model_output=_output("发生断裂"),
                attempts=1,
                preprocessing=None,
            )

    record = _visual_round(
        video_path=tmp_path / "demo.mp4",
        sample_range=[0.0, 40.0],
        inference_client=NoMetadataClient(),
        clip_builder=RecordingClipBuilder(),
    )

    assert record["ok"] is False
    assert record["model_output"] is None
    assert record["infra_error"]["code"] == "missing_or_invalid_preprocessing_metadata"
    mapped = map_single_call(record)
    assert mapped["status"] == "unrecognized"


def test_delivery_bundle_generator_marks_unattested_checks_unverified(
    tmp_path: Path,
) -> None:
    gate_empty = _load_delivery_gate(None)
    assert gate_empty["overall_passed"] is False
    assert all(
        gate_empty["checks"][name] == "unverified" for name in REQUIRED_DELIVERY_CHECKS
    )

    partial_record = tmp_path / "partial.json"
    partial_record.write_text(
        json.dumps({"checks": {"agent_tests_passed": True, "web_build_passed": True}}),
        encoding="utf-8",
    )
    gate_partial = _load_delivery_gate(partial_record)
    assert gate_partial["overall_passed"] is False
    assert gate_partial["checks"]["agent_tests_passed"] is True
    assert gate_partial["checks"]["real_video_remote_gpu_call_passed"] == "unverified"

    full_record = tmp_path / "full.json"
    full_record.write_text(
        json.dumps({"checks": {name: True for name in REQUIRED_DELIVERY_CHECKS}}),
        encoding="utf-8",
    )
    gate_full = _load_delivery_gate(full_record)
    assert gate_full["overall_passed"] is True
    assert all(gate_full["checks"][name] is True for name in REQUIRED_DELIVERY_CHECKS)
