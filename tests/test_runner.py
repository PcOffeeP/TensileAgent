from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent import runner


class TestLoadConfig:
    def test_load_config_success(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "llm:\n  model: test-model\n  base_url: http://localhost\n",
            encoding="utf-8",
        )

        config = runner.load_config(config_path)

        assert config == {
            "llm": {"model": "test-model", "base_url": "http://localhost"}
        }


class TestBuildVideoMeta:
    def test_ffprobe_success(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        video_path = tmp_path / "test_video.mp4"
        video_path.write_text("fake video content", encoding="utf-8")

        monkeypatch.setattr("agent.sampling._which_ffprobe", lambda: "/usr/bin/ffprobe")
        monkeypatch.setattr(
            "agent.sampling._probe_video",
            lambda path: {
                "duration": 12.5,
                "fps": 25.0,
                "total_frames": 312,
            },
        )

        meta = runner.build_video_meta(video_path)

        assert meta["video_id"] == "test_video"
        assert meta["video_path"] == str(video_path)
        assert meta["duration_sec"] == 12.5
        assert meta["duration"] == 12.5
        assert meta["original_fps"] == 25.0
        assert meta["total_frames"] == 312

    def test_ffprobe_fails_cv2_success(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video_path = tmp_path / "test_video.mp4"
        video_path.write_text("fake video content", encoding="utf-8")

        def _raise() -> str:
            raise RuntimeError("ffprobe not found")

        monkeypatch.setattr("agent.sampling._which_ffprobe", _raise)
        monkeypatch.setattr(
            "agent.sampling._probe_video", lambda path: (_ for _ in ()).throw(RuntimeError("probe failed"))
        )

        fake_cv2 = types.ModuleType("cv2")
        fake_cv2.CAP_PROP_FPS = 5
        fake_cv2.CAP_PROP_FRAME_COUNT = 7
        cap = MagicMock()
        cap.isOpened.return_value = True
        cap.get.side_effect = lambda prop: {
            fake_cv2.CAP_PROP_FPS: 24.0,
            fake_cv2.CAP_PROP_FRAME_COUNT: 240,
        }.get(prop, 0.0)
        cap.release = MagicMock()
        fake_cv2.VideoCapture = MagicMock(return_value=cap)
        monkeypatch.setitem(sys.modules, "cv2", fake_cv2)

        meta = runner.build_video_meta(video_path)

        assert meta["duration_sec"] == 10.0
        assert meta["original_fps"] == 24.0
        assert meta["total_frames"] == 240

    def test_both_fail_raises_runtime_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        video_path = tmp_path / "test_video.mp4"
        video_path.write_text("fake video content", encoding="utf-8")

        def _raise() -> str:
            raise RuntimeError("ffprobe not found")

        monkeypatch.setattr("agent.sampling._which_ffprobe", _raise)
        monkeypatch.setattr(
            "agent.sampling._probe_video", lambda path: (_ for _ in ()).throw(RuntimeError("probe failed"))
        )

        fake_cv2 = types.ModuleType("cv2")
        fake_cv2.CAP_PROP_FPS = 5
        fake_cv2.CAP_PROP_FRAME_COUNT = 7
        cap = MagicMock()
        cap.isOpened.return_value = False
        fake_cv2.VideoCapture = MagicMock(return_value=cap)
        monkeypatch.setitem(sys.modules, "cv2", fake_cv2)

        with pytest.raises(RuntimeError, match="cv2 unable to open video"):
            runner.build_video_meta(video_path)


class TestRunOne:
    @patch("agent.iterative_agent.IterativeAgent")
    @patch("agent.runner.create_clip_builder")
    @patch("agent.runner.create_inference_client")
    @patch("agent.runner.create_llm_client")
    @patch("agent.runner.build_video_meta")
    def test_run_one_creates_agent_and_calls_run(
        self,
        mock_build_video_meta: MagicMock,
        mock_create_llm_client: MagicMock,
        mock_create_inference_client: MagicMock,
        mock_create_clip_builder: MagicMock,
        mock_iterative_agent: MagicMock,
        tmp_path: Path,
    ) -> None:
        video_path = tmp_path / "sample.mp4"
        video_path.write_text("fake video content", encoding="utf-8")

        video_meta = {
            "video_id": "sample",
            "video_path": str(video_path),
            "duration_sec": 8.0,
        }
        mock_build_video_meta.return_value = video_meta
        mock_llm_client = MagicMock()
        mock_inference_client = MagicMock()
        mock_clip_builder = MagicMock()
        mock_create_llm_client.return_value = mock_llm_client
        mock_create_inference_client.return_value = mock_inference_client
        mock_create_clip_builder.return_value = mock_clip_builder

        mock_agent_instance = MagicMock()
        mock_agent_instance.run.return_value = {
            "video_id": "sample",
            "status": "no_fracture",
            "confidence": 0.95,
        }
        mock_iterative_agent.return_value = mock_agent_instance

        config = {"llm": {"model": "test"}}
        with patch("agent.runner.load_config", return_value=config) as mock_load_config:
            result = runner.run_one(video_path, config_path="agent/config.yaml")

        assert isinstance(result, dict)
        assert result["ok"] is True
        assert result["error"] is None
        assert result["result"]["video_id"] == "sample"
        assert result["result"]["status"] == "no_fracture"
        assert result["result"]["confidence"] is None
        mock_load_config.assert_called_once_with("agent/config.yaml")
        mock_build_video_meta.assert_called_once_with(video_path, video_id="sample")
        mock_create_llm_client.assert_called_once_with(config)
        mock_create_inference_client.assert_called_once_with(config)
        mock_create_clip_builder.assert_called_once()
        mock_iterative_agent.assert_called_once()
        mock_agent_instance.run.assert_called_once()

    @patch("agent.iterative_agent.IterativeAgent")
    @patch("agent.runner.create_clip_builder")
    @patch("agent.runner.create_inference_client")
    @patch("agent.runner.create_llm_client")
    @patch("agent.runner.build_video_meta")
    def test_run_one_passes_event_callback_to_agent(
        self,
        mock_build_video_meta: MagicMock,
        mock_create_llm_client: MagicMock,
        mock_create_inference_client: MagicMock,
        mock_create_clip_builder: MagicMock,
        mock_iterative_agent: MagicMock,
        tmp_path: Path,
    ) -> None:
        video_path = tmp_path / "sample.mp4"
        video_path.write_text("fake video content", encoding="utf-8")

        mock_build_video_meta.return_value = {
            "video_id": "sample",
            "video_path": str(video_path),
            "duration_sec": 8.0,
        }
        mock_iterative_agent.return_value = MagicMock()

        callback = MagicMock()
        config = {"llm": {"model": "test"}}
        with patch("agent.runner.load_config", return_value=config):
            runner.run_one(
                video_path,
                config_path="agent/config.yaml",
                event_callback=callback,
            )

        call_kwargs = mock_iterative_agent.call_args.kwargs
        assert call_kwargs["event_callback"] is callback

    @patch("agent.iterative_agent.IterativeAgent")
    @patch("agent.runner.create_clip_builder")
    @patch("agent.runner.create_inference_client")
    @patch("agent.runner.create_llm_client")
    @patch("agent.runner.build_video_meta")
    def test_run_one_passes_work_dir_to_agent(
        self,
        mock_build_video_meta: MagicMock,
        mock_create_llm_client: MagicMock,
        mock_create_inference_client: MagicMock,
        mock_create_clip_builder: MagicMock,
        mock_iterative_agent: MagicMock,
        tmp_path: Path,
    ) -> None:
        video_path = tmp_path / "sample.mp4"
        video_path.write_text("fake video content", encoding="utf-8")

        mock_build_video_meta.return_value = {
            "video_id": "sample",
            "video_path": str(video_path),
            "duration_sec": 8.0,
        }
        mock_iterative_agent.return_value = MagicMock()

        work_dir = tmp_path / "runs"
        config = {"llm": {"model": "test"}}
        with patch("agent.runner.load_config", return_value=config):
            runner.run_one(
                video_path,
                config_path="agent/config.yaml",
                work_dir=str(work_dir),
            )

        call_kwargs = mock_iterative_agent.call_args.kwargs
        assert call_kwargs["work_dir"] == str(work_dir)

    @patch("agent.iterative_agent.IterativeAgent")
    @patch("agent.runner.create_clip_builder")
    @patch("agent.runner.create_inference_client")
    @patch("agent.runner.create_llm_client")
    @patch("agent.runner.build_video_meta")
    def test_run_one_propagates_runner_failure_envelope(
        self,
        mock_build_video_meta: MagicMock,
        mock_create_llm_client: MagicMock,
        mock_create_inference_client: MagicMock,
        mock_create_clip_builder: MagicMock,
        mock_iterative_agent: MagicMock,
        tmp_path: Path,
    ) -> None:
        """``run_one`` must propagate ``RunnerResult(ok=False, ...)`` from the agent.

        Without this check the success branch tries to build a ``FinalOutput``
        from the error dict and masks the original ``consecutive_infra_failures``
        code with a generic ``ValidationError``.
        """
        video_path = tmp_path / "sample.mp4"
        video_path.write_text("fake video content", encoding="utf-8")

        mock_build_video_meta.return_value = {
            "video_id": "sample",
            "video_path": str(video_path),
            "duration_sec": 8.0,
        }
        mock_iterative_agent.return_value = MagicMock()
        failure_envelope = {
            "ok": False,
            "result": None,
            "error": {
                "stage": "internal",
                "code": "consecutive_infra_failures",
                "message": "连续 2 轮基础设施失败，无法完成分析",
            },
        }
        mock_iterative_agent.return_value.run.return_value = failure_envelope

        callback = MagicMock()
        config = {"llm": {"model": "test"}}
        with patch("agent.runner.load_config", return_value=config):
            result = runner.run_one(
                video_path,
                config_path="agent/config.yaml",
                event_callback=callback,
            )

        assert result == failure_envelope
        assert result["error"]["code"] == "consecutive_infra_failures"

        callback.assert_called_once()
        event = callback.call_args.args[0]
        assert event["event_type"] == "video_failed"
        assert event["video_id"] == "sample"
        assert event["stage"] == "internal"
        assert "基础设施失败" in event["error"]

    @patch("agent.iterative_agent.IterativeAgent")
    @patch("agent.runner.create_clip_builder")
    @patch("agent.runner.create_inference_client")
    @patch("agent.runner.create_llm_client")
    @patch("agent.runner.build_video_meta")
    def test_run_one_failure_emits_video_failed_and_returns_error(
        self,
        mock_build_video_meta: MagicMock,
        mock_create_llm_client: MagicMock,
        mock_create_inference_client: MagicMock,
        mock_create_clip_builder: MagicMock,
        mock_iterative_agent: MagicMock,
        tmp_path: Path,
    ) -> None:
        video_path = tmp_path / "sample.mp4"
        video_path.write_text("fake video content", encoding="utf-8")

        mock_build_video_meta.side_effect = RuntimeError("metadata extraction failed")

        callback = MagicMock()
        config = {"llm": {"model": "test"}}

        with patch("agent.runner.load_config", return_value=config):
            result = runner.run_one(
                video_path,
                config_path="agent/config.yaml",
                event_callback=callback,
            )

        assert isinstance(result, dict)
        assert result["ok"] is False
        assert result["result"] is None
        assert result["error"]["stage"] == "input"
        assert result["error"]["code"] == "RuntimeError"
        assert result["error"]["message"] == "metadata extraction failed"

        callback.assert_called_once()
        event = callback.call_args.args[0]
        assert event["event_type"] == "video_failed"
        assert event["video_id"] == "sample"
        assert event["error"] == "metadata extraction failed"
        assert event["stage"] == "input"

    def test_run_one_load_config_failure_emits_video_failed_and_returns_error(
        self, tmp_path: Path
    ) -> None:
        video_path = tmp_path / "fake.mp4"
        video_path.write_text("fake video content", encoding="utf-8")

        callback = MagicMock()
        with patch("agent.runner.load_config", side_effect=RuntimeError("config broken")):
            result = runner.run_one(
                video_path,
                config_path="agent/config.yaml",
                event_callback=callback,
            )

        assert isinstance(result, dict)
        assert result["ok"] is False
        assert result["result"] is None
        assert result["error"]["stage"] == "configuration"
        assert result["error"]["code"] == "RuntimeError"
        assert result["error"]["message"] == "config broken"

        callback.assert_called_once()
        event = callback.call_args.args[0]
        assert event["event_type"] == "video_failed"
        assert event["video_id"] == "fake"
        assert event["error"] == "config broken"
        assert event["stage"] == "configuration"


class TestRunBatch:
    @patch("agent.runner.run_one")
    def test_run_batch_executes_sequentially(
        self, mock_run_one: MagicMock, tmp_path: Path
    ) -> None:
        video1 = tmp_path / "v1.mp4"
        video2 = tmp_path / "v2.mp4"
        video1.write_text("fake", encoding="utf-8")
        video2.write_text("fake", encoding="utf-8")

        mock_run_one.side_effect = [
            {
                "ok": True,
                "result": {"video_id": "v1", "status": "no_fracture", "confidence": 0.9},
                "error": None,
            },
            {
                "ok": True,
                "result": {"video_id": "v2", "status": "no_fracture", "confidence": 0.85},
                "error": None,
            },
        ]

        callback = MagicMock()
        config_path = "agent/config.yaml"
        with patch("agent.runner.load_config") as mock_load_config:
            results = runner.run_batch(
                [video1, video2],
                config_path=config_path,
                event_callback=callback,
            )

        mock_load_config.assert_not_called()
        assert len(results) == 2
        assert results[0]["ok"] is True
        assert results[0]["result"]["video_id"] == "v1"
        assert results[1]["ok"] is True
        assert results[1]["result"]["video_id"] == "v2"
        assert mock_run_one.call_count == 2
        assert mock_run_one.call_args_list[0].args[0] == video1
        assert mock_run_one.call_args_list[1].args[0] == video2
        assert mock_run_one.call_args_list[0].args[1] == config_path
        assert mock_run_one.call_args_list[1].args[1] == config_path
        for call in mock_run_one.call_args_list:
            assert call.kwargs["event_callback"] is callback

    @patch("agent.runner.run_one")
    def test_run_batch_failure_does_not_interrupt(
        self, mock_run_one: MagicMock, tmp_path: Path
    ) -> None:
        video1 = tmp_path / "v1.mp4"
        video2 = tmp_path / "v2.mp4"
        video1.write_text("fake", encoding="utf-8")
        video2.write_text("fake", encoding="utf-8")

        def _side_effect(
            path: str | Path,
            config_path: str | Path,
            video_id: str | None = None,
            event_callback=None,
            work_dir=None,
            **kwargs,
        ) -> dict:
            if Path(path).name == "v1.mp4":
                return {
                    "ok": False,
                    "result": None,
                    "error": {
                        "stage": "inference_transport",
                        "code": "RuntimeError",
                        "message": "inference timeout",
                    },
                }
            return {
                "ok": True,
                "result": {"video_id": video_id, "status": "no_fracture", "confidence": 0.9},
                "error": None,
            }

        mock_run_one.side_effect = _side_effect

        with patch("agent.runner.load_config", return_value={"llm": {"model": "test"}}):
            results = runner.run_batch(
                [video1, video2],
                config_path="agent/config.yaml",
            )

        assert len(results) == 2
        assert results[0]["ok"] is False
        assert results[0]["result"] is None
        assert results[0]["error"]["stage"] == "inference_transport"
        assert results[0]["error"]["code"] == "RuntimeError"
        assert results[0]["error"]["message"] == "inference timeout"
        assert results[1]["ok"] is True
        assert results[1]["result"]["video_id"] == "v2"

    @patch("agent.runner.run_one")
    def test_run_batch_emits_video_failed_event(
        self, mock_run_one: MagicMock, tmp_path: Path
    ) -> None:
        video1 = tmp_path / "v1.mp4"
        video2 = tmp_path / "v2.mp4"
        video1.write_text("fake", encoding="utf-8")
        video2.write_text("fake", encoding="utf-8")

        def _side_effect(
            path: str | Path,
            config_path: str | Path,
            video_id: str | None = None,
            event_callback=None,
            work_dir=None,
            **kwargs,
        ) -> dict:
            if event_callback is not None and Path(path).name == "v1.mp4":
                event_callback(
                    {
                        "event_type": "video_failed",
                        "video_id": video_id,
                        "error": "metadata error",
                        "stage": "input",
                    }
                )
            if Path(path).name == "v1.mp4":
                return {
                    "ok": False,
                    "result": None,
                    "error": {
                        "stage": "input",
                        "code": "RuntimeError",
                        "message": "metadata error",
                    },
                }
            return {
                "ok": True,
                "result": {"video_id": video_id, "status": "no_fracture", "confidence": 0.9},
                "error": None,
            }

        mock_run_one.side_effect = _side_effect
        callback = MagicMock()

        with patch("agent.runner.load_config", return_value={"llm": {"model": "test"}}):
            runner.run_batch(
                [video1, video2],
                config_path="agent/config.yaml",
                event_callback=callback,
            )

        callback.assert_called_once()
        event = callback.call_args.args[0]
        assert event["event_type"] == "video_failed"
        assert event["video_id"] == "v1"
        assert event["error"] == "metadata error"
        assert event["stage"] == "input"


class TestEventsJsonSerializable:
    @patch("agent.iterative_agent.IterativeAgent")
    @patch("agent.runner.create_clip_builder")
    @patch("agent.runner.create_inference_client")
    @patch("agent.runner.create_llm_client")
    @patch("agent.runner.build_video_meta")
    def test_all_events_are_json_serializable(
        self,
        mock_build_video_meta: MagicMock,
        mock_create_llm_client: MagicMock,
        mock_create_inference_client: MagicMock,
        mock_create_clip_builder: MagicMock,
        mock_iterative_agent: MagicMock,
        tmp_path: Path,
    ) -> None:
        video_path = tmp_path / "sample.mp4"
        video_path.write_text("fake video content", encoding="utf-8")

        mock_build_video_meta.return_value = {
            "video_id": "sample",
            "video_path": str(video_path),
            "duration_sec": 8.0,
        }

        events: list[dict] = []

        def callback(event: dict) -> None:
            events.append(event)

        def _fake_run() -> dict:
            callback({"event_type": "video_started", "video_id": "sample", "duration": 8.0})
            callback(
                {
                    "event_type": "round_started",
                    "video_id": "sample",
                    "round": 1,
                    "state": "initial",
                    "candidate": [0.0, 8.0],
                }
            )
            callback(
                {
                    "event_type": "llm_tool_call",
                    "round": 1,
                    "tool_name": "sample_and_infer",
                    "tool_args": {"sample_range": [0.0, 8.0], "num_frames": 4},
                }
            )
            callback(
                {
                    "event_type": "video_finished",
                    "video_id": "sample",
                    "result": {"has_fracture": True, "time_range": [3.0, 5.0]},
                }
            )
            return {
                "video_id": "sample",
                "status": "fracture",
                "time_range": [3.0, 5.0],
                "fracture_type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.85,
            }

        mock_agent_instance = MagicMock()
        mock_agent_instance.run = _fake_run
        mock_iterative_agent.return_value = mock_agent_instance

        with patch("agent.runner.load_config", return_value={"llm": {"model": "test"}}):
            runner.run_one(
                video_path,
                config_path="agent/config.yaml",
                event_callback=callback,
            )

        # Also include a video_failed event in the serialization check.
        callback(
            {
                "event_type": "video_failed",
                "video_id": "sample",
                "error": "metadata error",
                "stage": "input",
            }
        )

        assert len(events) >= 5
        for event in events:
            serialized = json.dumps(event)
            assert isinstance(serialized, str)
