"""Web API 适配层契约测试（纯 mock，不依赖真实模型/视频/配置）"""
from __future__ import annotations

import asyncio
import io
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import agent.web_api as web_api
from agent.web_api import (
    TaskModel,
    _apply_runner_result_to_task,
    _event_callback_factory,
    _normalize_result,
    _sanitize_event_data,
    _to_public_task,
)


@pytest.fixture
def tmp_runtime(tmp_path, monkeypatch):
    """将 Web API 的运行时目录重定向到临时目录，避免污染真实数据。"""
    runtime = tmp_path / "runtime"
    uploads = runtime / "uploads"
    history = runtime / "history"
    events = runtime / "events"
    monkeypatch.setattr(web_api, "RUNTIME_DIR", runtime)
    monkeypatch.setattr(web_api, "UPLOADS_DIR", uploads)
    monkeypatch.setattr(web_api, "HISTORY_DIR", history)
    monkeypatch.setattr(web_api, "EVENTS_DIR", events)
    monkeypatch.setattr(web_api, "RUNTIME_INDEX_PATH", runtime / "private_runtime_index.json")
    monkeypatch.setattr(web_api, "LLM_TRACES_DIR", runtime / "llm_traces")
    runtime.mkdir(parents=True, exist_ok=True)
    uploads.mkdir(parents=True, exist_ok=True)
    history.mkdir(parents=True, exist_ok=True)
    events.mkdir(parents=True, exist_ok=True)
    web_api.tasks.clear()
    web_api.sse_connections.clear()
    monkeypatch.setattr(web_api, "task_queue", asyncio.Queue())
    yield runtime


@pytest.fixture
def client(tmp_runtime, monkeypatch):
    """使用临时目录和 dummy worker 的 TestClient。"""

    async def dummy_worker():
        while True:
            await asyncio.sleep(3600)

    monkeypatch.setattr(web_api, "_queue_worker", dummy_worker)
    monkeypatch.setattr(
        web_api,
        "_validated_model_snapshot",
        lambda: {
            "backend": "local",
            "provider": "ollama",
            "model": "tensile-qwen35:9b",
            "base_url": "http://localhost:11434/v1",
            "reasoning_effort": "none",
            "digest": "test-digest",
        },
    )
    with TestClient(web_api.app) as c:
        yield c


@pytest.fixture
def capture_events(monkeypatch):
    """捕获 _append_event 写入的事件。"""
    captured: list[dict] = []

    def fake_append_event(task_id: str, event: dict):
        captured.append({"task_id": task_id, **web_api._sanitize_event_data(event)})

    monkeypatch.setattr(web_api, "_append_event", fake_append_event)
    return captured


class TestNormalizeResult:
    def test_ok_true_extracts_result(self):
        runner_result = {
            "ok": True,
            "result": {
                "video_id": "sample",
                "status": "fracture",
                "time_range": [10.2, 10.8],
                "fracture_type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.91,
                "visual_evidence": {
                    "status": "available",
                    "summary": "试样分离。",
                    "references": [],
                },
                "unrecognized_reason": None,
            },
        }
        normalized = _normalize_result(runner_result)
        assert normalized["status"] == "fracture"
        assert normalized["video_id"] == "sample"
        assert normalized["time_range"] == [10.2, 10.8]
        assert normalized["fracture_type"] == "韧性断裂"
        assert normalized["location"] == "inside_gauge"
        assert normalized["confidence"] == 0.91
        assert normalized["visual_evidence"]["summary"] == "试样分离。"

    def test_ok_false_maps_to_failed(self):
        runner_result = {
            "ok": False,
            "error": {"stage": "sampling", "code": "sampling_error", "message": "boom"},
        }
        normalized = _normalize_result(runner_result)
        assert normalized["status"] == "failed"
        assert normalized["stage"] == "sampling"
        assert normalized["code"] == "sampling_error"

    def test_legacy_fallback_is_rejected(self):
        legacy = {
            "status": "fracture",
            "video_id": "legacy",
            "output": {"type": "韧性断裂", "location": "inside_gauge", "confidence": 0.8},
            "start_time": 5.0,
            "end_time": 6.0,
            "rounds": 3,
        }
        normalized = _normalize_result(legacy)
        assert normalized["schema_version"] == "tensile-agent/result/v2"
        assert normalized["status"] == "unrecognized"
        assert normalized["unrecognized_reason"] == "invalid_model_output"


class TestApplyRunnerResultToTask:
    def test_ok_true_completes_task(self, capture_events):
        task = TaskModel(id="t1", video_id="sample", video_name="sample.mp4", created_at="now")
        runner_result = {
            "ok": True,
            "result": {
                "video_id": "sample",
                "status": "fracture",
                "time_range": [1.0, 2.0],
                "fracture_type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.9,
            },
        }
        _apply_runner_result_to_task(task, runner_result)

        assert task.status == web_api.TASK_STATUS_COMPLETED
        assert task.result["status"] == "fracture"
        assert task.error is None
        assert any(e["event"] == "task_completed" for e in capture_events)
        assert not any(e["event"] == "task_failed" for e in capture_events)

    def test_ok_false_fails_task_and_emits_task_failed(self, capture_events):
        task = TaskModel(id="t2", video_id="sample", video_name="sample.mp4", created_at="now")
        runner_result = {
            "ok": False,
            "error": {"stage": "inference", "code": "timeout", "message": "inference timeout"},
        }
        _apply_runner_result_to_task(task, runner_result)

        assert task.status == web_api.TASK_STATUS_FAILED
        assert task.error == {"stage": "inference", "code": "timeout", "message": "inference timeout"}
        assert task.result is None
        assert any(e["event"] == "task_failed" for e in capture_events)
        assert not any(e["event"] == "task_completed" for e in capture_events)

    def test_apply_runner_result_ok_false_non_dict_error_fallback(self, capture_events):
        task = TaskModel(id="t3", video_id="sample", video_name="sample.mp4", created_at="now")
        runner_result = {"ok": False, "error": "connection timeout"}
        _apply_runner_result_to_task(task, runner_result)

        assert task.status == web_api.TASK_STATUS_FAILED
        assert task.error == {
            "stage": "runner",
            "code": "unknown_error",
            "message": "connection timeout",
        }

    def test_apply_runner_result_ok_false_result_is_none(self, capture_events):
        task = TaskModel(id="t4", video_id="sample", video_name="sample.mp4", created_at="now")
        runner_result = {
            "ok": False,
            "error": {"stage": "inference", "code": "timeout", "message": "inference timeout"},
        }
        _apply_runner_result_to_task(task, runner_result)

        assert task.status == web_api.TASK_STATUS_FAILED
        assert task.result is None

    def test_apply_runner_result_ok_false_task_failed_event_sanitized(self, capture_events):
        task = TaskModel(id="t5", video_id="sample", video_name="sample.mp4", created_at="now")
        runner_result = {
            "ok": False,
            "error": {
                "stage": "runner",
                "code": "file_not_found",
                "message": "missing /secret/demo.mp4",
            },
        }
        _apply_runner_result_to_task(task, runner_result)

        failed_event = next(e for e in capture_events if e["event"] == "task_failed")
        assert failed_event["data"]["message"] == "missing <path:redacted>"
        assert "/secret" not in json.dumps(failed_event)


class TestEventCallbackFactory:
    def test_maps_event_type_to_top_level(self, capture_events):
        callback = _event_callback_factory("t1")
        callback({"event_type": "round_started", "round": 1, "display_round": 2})

        event = capture_events[0]
        assert event["event"] == "round_started"
        assert event["data"]["event_type"] == "round_started"
        assert event["data"]["round"] == 1

    def test_video_finished_passes_through(self, capture_events):
        callback = _event_callback_factory("t2")
        callback({"event_type": "video_finished", "result": {"status": "fracture"}})

        event = capture_events[0]
        assert event["event"] == "video_finished"
        assert event["data"]["event_type"] == "video_finished"

    def test_video_failed_event_sanitized(self, capture_events):
        callback = _event_callback_factory("t2")
        callback({
            "event_type": "video_failed",
            "error": {
                "stage": "runner",
                "code": "file_not_found",
                "message": "missing /secret/video.mp4",
            },
        })

        event = capture_events[0]
        assert event["event"] == "video_failed"
        assert event["data"]["error"]["message"] == "missing <path:redacted>"
        assert "/secret" not in json.dumps(event)

    def test_empty_event_type_falls_back_to_event_field(self, capture_events):
        callback = _event_callback_factory("t3")
        callback({"event_type": "", "event": "round_started", "round": 1})

        event = capture_events[0]
        assert event["event"] == "round_started"

    def test_unknown_when_both_missing(self, capture_events):
        callback = _event_callback_factory("t4")
        callback({})

        event = capture_events[0]
        assert event["event"] == "unknown"


class TestSanitizeEventData:
    def test_redacts_sensitive_keys(self):
        raw = {
            "base64": "aGVsbG8=",
            "token": "sk-123",
            "api_key": "secret",
            "video_path": "/tmp/video.mp4",
            "model_video_path": "/tmp/model.mp4",
            "clip_path": "/tmp/clip.mp4",
            "temp_path": "/tmp/temp.mp4",
            "config_path": "/tmp/config.yaml",
        }
        safe = _sanitize_event_data(raw)
        assert all(v == "<redacted>" for v in safe.values())

    def test_path_values_default_to_basename(self):
        raw = {
            "text": "/home/user/video.mp4",
            "items": ["C:\\Users\\foo\\bar.mp4", "plain text"],
        }
        safe = _sanitize_event_data(raw)
        assert safe["text"] == "video.mp4"
        assert safe["items"] == ["bar.mp4", "plain text"]

    def test_runtime_clip_config_paths_redacted(self):
        raw = {
            "runtime_dir": "/data/08_runtime",
            "clip_dir": "C:\\clips\\secret",
            "config_dir": "/etc/agent",
        }
        safe = _sanitize_event_data(raw)
        assert safe["runtime_dir"] == "<redacted>"
        assert safe["clip_dir"] == "<redacted>"
        assert safe["config_dir"] == "<redacted>"

    def test_windows_forward_slash_path_redacted(self):
        raw = {
            "path": "C:/tmp/clip.mp4",
            "items": ["C:/Users/foo/bar.mp4", "plain text"],
        }
        safe = _sanitize_event_data(raw)
        assert safe["path"] == "clip.mp4"
        assert safe["items"] == ["bar.mp4", "plain text"]

    def test_message_paths_redacted_to_path_placeholder(self):
        raw = {
            "message": "file not found: /Users/demo/project/clip.mp4",
            "error_message": "failed to read C:\\Users\\demo\\clip.mp4",
        }
        safe = _sanitize_event_data(raw)
        assert safe["message"] == "file not found: <path:redacted>"
        assert safe["error_message"] == "failed to read <path:redacted>"

    def test_data_uri_redacted(self):
        raw = {
            "payload": "data:video/mp4;base64,AAAAIGZ0eXBpc29tAAACAGlzb21pc28y",
            "text": "prefix data:application/json;base64,eyJhIjoxfQ suffix",
        }
        safe = _sanitize_event_data(raw)
        assert safe["payload"] == "<data:redacted>"
        assert safe["text"] == "prefix <data:redacted> suffix"

    def test_bearer_token_redacted(self):
        raw = {"auth": "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"}
        safe = _sanitize_event_data(raw)
        assert safe["auth"] == "Authorization: <token:redacted>"

    def test_api_key_redacted(self):
        raw = {
            "note": "key is sk-abc123DEF kept secret",
            "nested": {"value": "prefix sk-test-12345 suffix"},
        }
        safe = _sanitize_event_data(raw)
        assert safe["note"] == "key is <api_key:redacted> kept secret"
        assert safe["nested"]["value"] == "prefix <api_key:redacted> suffix"

    def test_url_preservation_and_path_redaction(self):
        raw = {
            "message": "check URL http://example.com/a/b and file /Users/demo/path.mp4",
            "error_message": "failed to access C:\\Users\\demo\\path.mp4 via https://127.0.0.1:8765/api/tasks",
        }
        safe = _sanitize_event_data(raw)
        assert safe["message"] == "check URL http://example.com/a/b and file <path:redacted>"
        assert safe["error_message"] == "failed to access <path:redacted> via https://127.0.0.1:8765/api/tasks"


class TestPublicTaskConversion:
    def test_public_task_excludes_internal_paths(self):
        task = TaskModel(
            id="t1",
            video_id="sample",
            video_name="sample.mp4",
            video_path="/secret/path/sample.mp4",
            created_at="now",
            result={"status": "fracture"},
        )
        public = _to_public_task(task)
        assert "video_path" not in public
        assert public["video_name"] == "sample.mp4"
        assert public["status"] == web_api.TASK_STATUS_QUEUED

    def test_public_task_sanitizes_result_and_error_paths(self):
        task = TaskModel(
            id="t1",
            video_id="sample",
            video_name="sample.mp4",
            created_at="now",
            result={"status": "ok", "message": "/secret/result.txt"},
            error={"stage": "runner", "code": "error", "message": "/secret/tmp/clip.mp4"},
        )
        public = _to_public_task(task)
        assert public["result"]["message"] == "<path:redacted>"
        assert public["error"]["message"] == "<path:redacted>"

    def test_public_task_sanitizes_event_summary(self):
        task = TaskModel(
            id="t1",
            video_id="sample",
            video_name="sample.mp4",
            created_at="now",
            event_summary={
                "video_path": "/secret/video.mp4",
                "api_key": "sk-123",
                "runtime_dir": "/data/08_runtime/secret",
                "items": ["/tmp/a.mp4", "plain text"],
            },
        )
        public = _to_public_task(task)
        assert public["event_summary"]["video_path"] == "<redacted>"
        assert public["event_summary"]["api_key"] == "<redacted>"
        assert public["event_summary"]["runtime_dir"] == "<redacted>"
        assert public["event_summary"]["items"] == ["a.mp4", "plain text"]

    def test_public_task_event_summary_none_is_safe(self):
        task = TaskModel(
            id="t1",
            video_id="sample",
            video_name="sample.mp4",
            created_at="now",
        )
        public = _to_public_task(task)
        assert public["event_summary"] is None


class TestQueueWorker:
    def test_exception_emits_sanitized_task_failed(self, tmp_runtime, monkeypatch):
        task = TaskModel(
            id="t_fail",
            video_id="demo",
            video_name="demo.mp4",
            created_at="now",
            video_path="/tmp/demo.mp4",
        )
        web_api.tasks[task.id] = task

        def fake_run_one(*args, **kwargs):
            # 异常 message 本身是一个绝对路径，用于验证传入 _append_event 前已被脱敏
            raise RuntimeError("/tmp/secret/clip.mp4")

        monkeypatch.setattr(web_api, "run_one", fake_run_one)

        captured: list[dict] = []

        def fake_append_event(task_id: str, event: dict):
            captured.append({"task_id": task_id, **event})

        monkeypatch.setattr(web_api, "_append_event", fake_append_event)

        async def run():
            await web_api.task_queue.put(task.id)
            worker = asyncio.create_task(web_api._queue_worker())
            for _ in range(50):
                if any(e.get("event") == "task_failed" for e in captured):
                    break
                await asyncio.sleep(0.1)
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass

        asyncio.run(run())

        assert task.status == web_api.TASK_STATUS_FAILED
        failed_event = next(e for e in captured if e.get("event") == "task_failed")
        assert failed_event["data"]["stage"] == "runner"
        assert failed_event["data"]["code"] == "RuntimeError"
        # 原始 message 为绝对路径，传入 _append_event 前已被脱敏
        assert failed_event["data"]["message"] == "<path:redacted>"


class TestEndpoints:
    def test_create_task_from_path_returns_public_task(self, client, tmp_runtime):
        video = tmp_runtime / "uploads" / "test.mp4"
        video.write_text("fake video")

        resp = client.post("/api/tasks", data={"video_path": str(video), "video_id": "demo"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["video_id"] == "demo"
        assert data["video_name"] == "test.mp4"
        assert "video_path" not in data
        assert data["status"] == web_api.TASK_STATUS_QUEUED

    def test_create_task_pins_complete_decision_model_snapshot(
        self, client, tmp_runtime, monkeypatch
    ):
        video = tmp_runtime / "uploads" / "snapshot.mp4"
        video.write_text("fake video")
        snapshot = {
            "backend": "local",
            "provider": "ollama",
            "model": "tensile-qwen35:9b",
            "base_url": "http://localhost:11434/v1",
            "reasoning_effort": "none",
            "digest": "sha256:pinned",
        }
        monkeypatch.setattr(web_api, "_validated_model_snapshot", lambda: snapshot.copy())

        resp = client.post(
            "/api/tasks", data={"video_path": str(video), "video_id": "snapshot"}
        )

        assert resp.status_code == 200
        task = web_api.tasks[resp.json()["task_id"]]
        assert task.decision_model == snapshot
        assert resp.json()["decision_model"] == snapshot

    def test_get_task_returns_public_task(self, client):
        task = TaskModel(
            id="t1",
            video_id="demo",
            video_name="demo.mp4",
            video_path="/secret/demo.mp4",
            created_at="now",
        )
        web_api.tasks["t1"] = task
        web_api._save_task(task)

        resp = client.get("/api/tasks/t1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["video_name"] == "demo.mp4"
        assert "video_path" not in data

    def test_replay_events_match_sse_and_sanitized(self, client, tmp_runtime):
        task = TaskModel(id="t1", video_id="demo", video_name="demo.mp4", created_at="now")
        web_api.tasks["t1"] = task
        web_api._save_task(task)
        web_api._append_event(
            "t1",
            {
                "task_id": "t1",
                "event": "task_created",
                "data": {"video_id": "demo", "video_path": "/secret/demo.mp4"},
                "timestamp": "2024-01-01T00:00:00",
            },
        )

        resp = client.get("/api/tasks/t1/events/replay")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) == 1
        ev = events[0]
        assert ev["event"] == "task_created"
        assert ev["data"]["video_path"] == "<redacted>"
        assert ev["data"]["video_id"] == "demo"

    def test_replay_events_unknown_when_data_both_missing(self, client, tmp_runtime):
        task = TaskModel(id="t1", video_id="demo", video_name="demo.mp4", created_at="now")
        web_api.tasks["t1"] = task
        web_api._save_task(task)

        events_path = web_api.EVENTS_DIR / "t1.jsonl"
        events_path.write_text(
            json.dumps(
                {
                    "task_id": "t1",
                    "data": {},
                    "timestamp": "2024-01-01T00:00:00",
                },
                ensure_ascii=False,
            )
            + "\n"
        )

        resp = client.get("/api/tasks/t1/events/replay")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) == 1
        assert events[0]["event"] == "unknown"

    def test_replay_events_fill_event_from_data_event_type(self, client, tmp_runtime):
        task = TaskModel(id="t1", video_id="demo", video_name="demo.mp4", created_at="now")
        web_api.tasks["t1"] = task
        web_api._save_task(task)

        events_path = web_api.EVENTS_DIR / "t1.jsonl"
        events_path.write_text(
            json.dumps(
                {
                    "task_id": "t1",
                    "data": {"event_type": "round_started", "round": 1},
                    "timestamp": "2024-01-01T00:00:00",
                },
                ensure_ascii=False,
            )
            + "\n"
        )

        resp = client.get("/api/tasks/t1/events/replay")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) == 1
        assert events[0]["event"] == "round_started"

    def test_replay_events_fill_event_from_data_event_field(self, client, tmp_runtime):
        task = TaskModel(id="t1", video_id="demo", video_name="demo.mp4", created_at="now")
        web_api.tasks["t1"] = task
        web_api._save_task(task)

        events_path = web_api.EVENTS_DIR / "t1.jsonl"
        events_path.write_text(
            json.dumps(
                {
                    "task_id": "t1",
                    "data": {"event": "round_started", "round": 1},
                    "timestamp": "2024-01-01T00:00:00",
                },
                ensure_ascii=False,
            )
            + "\n"
        )

        resp = client.get("/api/tasks/t1/events/replay")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) == 1
        assert events[0]["event"] == "round_started"

    def test_replay_events_skips_non_dict_lines(self, client, tmp_runtime):
        task = TaskModel(id="t1", video_id="demo", video_name="demo.mp4", created_at="now")
        web_api.tasks["t1"] = task
        web_api._save_task(task)

        events_path = web_api.EVENTS_DIR / "t1.jsonl"
        events_path.write_text(
            json.dumps(
                {
                    "task_id": "t1",
                    "event": "task_created",
                    "data": {"video_id": "demo"},
                    "timestamp": "2024-01-01T00:00:00",
                },
                ensure_ascii=False,
            )
            + "\n"
            + json.dumps("not a dict") + "\n"
            + json.dumps(["also", "not", "a", "dict"]) + "\n"
        )

        resp = client.get("/api/tasks/t1/events/replay")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) == 1
        assert events[0]["event"] == "task_created"

    def test_sse_does_not_replay_history(self, tmp_runtime):
        task = TaskModel(id="t1", video_id="demo", video_name="demo.mp4", created_at="now")
        web_api.tasks["t1"] = task
        web_api._save_task(task)

        events_path = web_api.EVENTS_DIR / "t1.jsonl"
        events_path.write_text(
            json.dumps(
                {
                    "task_id": "t1",
                    "event": "historical_event",
                    "data": {"x": 0},
                    "timestamp": "2024-01-01T00:00:00",
                },
                ensure_ascii=False,
            )
            + "\n"
        )

        async def run():
            response = await web_api.task_events("t1")
            queue = web_api.sse_connections["t1"][0]
            queue.put_nowait(
                {
                    "task_id": "t1",
                    "event": "live_event",
                    "data": {"x": 1},
                    "timestamp": "2024-01-01T00:00:01",
                }
            )

            chunks = []
            async for item in response.body_iterator:
                chunks.append(item)
                if "live_event" in item["data"]:
                    break

            data = "".join(c["data"] for c in chunks)
            assert "live_event" in data
            assert "historical_event" not in data

        asyncio.run(run())

    def test_export_csv_new_columns(self, client):
        task = TaskModel(
            id="t1",
            video_id="demo",
            video_name="demo.mp4",
            video_path="/secret/demo.mp4",
            created_at="now",
            status=web_api.TASK_STATUS_COMPLETED,
            result={
                "video_id": "demo",
                "status": "fracture",
                "time_range": [10.0, 11.0],
                "fracture_type": "韧性断裂",
                "location": "inside_gauge",
                "confidence": 0.85,
                "unrecognized_reason": None,
                "rounds": 4,
            },
        )
        web_api.tasks["t1"] = task
        web_api._save_task(task)

        resp = client.get("/api/tasks/t1/export?fmt=csv")
        assert resp.status_code == 200
        content = resp.text
        lines = [line.strip() for line in content.strip().splitlines()]
        header = lines[0].split(",")
        assert header == [
            "video_id",
            "status",
            "time_range_start",
            "time_range_end",
            "fracture_type",
            "location",
            "confidence",
            "unrecognized_reason",
            "rounds",
            "error_stage",
            "error_code",
            "error_message",
        ]
        row = lines[1].split(",")
        assert row[0] == "demo"
        assert row[1] == "fracture"
        assert row[2] == "10.0"
        assert row[3] == "11.0"
        assert row[8] == "4"

    def test_export_json_redacts_absolute_paths(self, client):
        task = TaskModel(
            id="t1",
            video_id="demo",
            video_name="demo.mp4",
            video_path="/secret/demo.mp4",
            created_at="now",
            status=web_api.TASK_STATUS_COMPLETED,
            result={
                "video_id": "demo",
                "status": "fracture",
                "report": "/secret/output/report.json",
                "message": "found at /secret/clip.mp4",
            },
        )
        web_api.tasks["t1"] = task
        web_api._save_task(task)

        resp = client.get("/api/tasks/t1/export?fmt=json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["report"] == "report.json"
        assert data["message"] == "found at <path:redacted>"
        assert "/secret" not in json.dumps(data)

    def test_export_csv_failed_task_includes_redacted_error(self, client):
        task = TaskModel(
            id="t1",
            video_id="demo",
            video_name="demo.mp4",
            video_path="/secret/demo.mp4",
            created_at="now",
            status=web_api.TASK_STATUS_FAILED,
            result={},
            error={
                "stage": "runner",
                "code": "file_not_found",
                "message": "missing /secret/demo.mp4",
            },
        )
        web_api.tasks["t1"] = task
        web_api._save_task(task)

        resp = client.get("/api/tasks/t1/export?fmt=csv")
        assert resp.status_code == 200
        content = resp.text
        lines = [line.strip() for line in content.strip().splitlines()]
        header = lines[0].split(",")
        row = lines[1].split(",")
        assert row[1] == "failed"
        stage_idx = header.index("error_stage")
        code_idx = header.index("error_code")
        message_idx = header.index("error_message")
        assert row[stage_idx] == "runner"
        assert row[code_idx] == "file_not_found"
        assert row[message_idx] == "missing <path:redacted>"
        assert "/secret" not in content

    def test_batch_returns_public_tasks(self, client):
        files = [
            ("files", ("a.mp4", io.BytesIO(b"video1"), "video/mp4")),
            ("files", ("b.mp4", io.BytesIO(b"video2"), "video/mp4")),
        ]
        resp = client.post("/api/tasks/batch", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tasks"]) == 2
        for task in data["tasks"]:
            assert "video_path" not in task
            assert task["video_name"] in ("a.mp4", "b.mp4")
            assert task["status"] == web_api.TASK_STATUS_QUEUED


class TestHistoryPersistence:
    def test_save_task_writes_public_history_and_runtime_index(self, tmp_runtime):
        task = TaskModel(
            id="t_pub",
            video_id="demo",
            video_name="demo.mp4",
            video_path=str(tmp_runtime / "uploads" / "demo.mp4"),
            config_path=str(tmp_runtime / "config.yaml"),
            question="什么时候断的，为什么？",
            created_at="2024-01-01T00:00:00",
            status=web_api.TASK_STATUS_COMPLETED,
            result={"status": "fracture", "note": "/secret/result.txt"},
        )
        web_api._save_task(task)

        history_file = web_api.HISTORY_DIR / "t_pub.json"
        assert history_file.exists()
        data = json.loads(history_file.read_text(encoding="utf-8"))
        assert data.get("_schema_version") == 2
        assert "video_path" not in data
        assert "config_path" not in data
        # 内部绝对路径已被脱敏，不会直接写入历史 JSON
        assert data["result"]["note"] == "result.txt"
        assert data["status"] == web_api.TASK_STATUS_COMPLETED
        assert data["question"] == "什么时候断的，为什么？"

        index = web_api._load_runtime_index()
        assert index["t_pub"]["video_path"] == str(tmp_runtime / "uploads" / "demo.mp4")
        assert index["t_pub"]["config_path"] == str(tmp_runtime / "config.yaml")

    def test_restore_history_public_format(self, tmp_runtime):
        task_id = "t_restore"
        history_file = web_api.HISTORY_DIR / f"{task_id}.json"
        history_file.write_text(
            json.dumps(
                {
                    "_schema_version": 2,
                    "id": task_id,
                    "status": web_api.TASK_STATUS_COMPLETED,
                    "video_id": "demo",
                    "video_name": "demo.mp4",
                    "question": "只告诉我是否断裂",
                    "created_at": "2024-01-01T00:00:00",
                    "result": {"status": "fracture"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        runtime_path = str(tmp_runtime / "uploads" / "demo.mp4")
        config_path = str(tmp_runtime / "config.yaml")
        web_api._save_runtime_index(
            {task_id: {"video_path": runtime_path, "config_path": config_path}}
        )

        web_api.tasks.clear()
        web_api._restore_history()

        assert task_id in web_api.tasks
        task = web_api.tasks[task_id]
        assert task.video_path == runtime_path
        assert task.config_path == config_path
        assert task.status == web_api.TASK_STATUS_COMPLETED
        assert task.question == "只告诉我是否断裂"
        assert web_api.task_queue.empty()

    def test_restore_history_public_format_missing_optional_video_name(self, tmp_runtime):
        task_id = "t_restore_no_video_name"
        history_file = web_api.HISTORY_DIR / f"{task_id}.json"
        history_file.write_text(
            json.dumps(
                {
                    "_schema_version": 2,
                    "id": task_id,
                    "status": web_api.TASK_STATUS_COMPLETED,
                    "video_id": "demo",
                    "created_at": "2024-01-01T00:00:00",
                    "result": {"status": "fracture"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        web_api.tasks.clear()
        web_api._restore_history()

        assert task_id in web_api.tasks
        task = web_api.tasks[task_id]
        assert task.video_name == ""
        assert task.status == web_api.TASK_STATUS_COMPLETED
        assert web_api.task_queue.empty()

    def test_restore_history_running_becomes_failed(self, tmp_runtime):
        task_id = "t_running"
        history_file = web_api.HISTORY_DIR / f"{task_id}.json"
        history_file.write_text(
            json.dumps(
                {
                    "_schema_version": 2,
                    "id": task_id,
                    "status": web_api.TASK_STATUS_RUNNING,
                    "video_id": "demo",
                    "video_name": "demo.mp4",
                    "created_at": "2024-01-01T00:00:00",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        web_api.tasks.clear()
        web_api._restore_history()

        task = web_api.tasks[task_id]
        assert task.status == web_api.TASK_STATUS_FAILED
        assert task.error["code"] == "restart"
        assert web_api.task_queue.empty()

    def test_restore_history_migrates_old_format(self, tmp_runtime):
        task_id = "t_old"
        video_dir = tmp_runtime / "uploads"
        video_dir.mkdir(parents=True, exist_ok=True)
        video_file = video_dir / "old.mp4"
        video_file.write_text("dummy video content")
        video_path = str(video_file)
        config_path = str(tmp_runtime / "old_config.yaml")
        old_data = {
            "_schema_version": 1,
            "id": task_id,
            "status": web_api.TASK_STATUS_QUEUED,
            "video_id": "old",
            "video_name": "old.mp4",
            "video_path": video_path,
            "config_path": config_path,
            "created_at": "2024-01-01T00:00:00",
        }
        history_file = web_api.HISTORY_DIR / f"{task_id}.json"
        history_file.write_text(json.dumps(old_data, ensure_ascii=False), encoding="utf-8")

        web_api.tasks.clear()
        web_api._restore_history()

        index = web_api._load_runtime_index()
        assert index[task_id]["video_path"] == video_path
        assert index[task_id]["config_path"] == config_path

        new_data = json.loads(history_file.read_text(encoding="utf-8"))
        assert new_data.get("_schema_version") == 2
        assert "video_path" not in new_data
        assert "config_path" not in new_data

        task = web_api.tasks[task_id]
        assert task.video_path == video_path
        assert task.config_path == config_path
        assert task.status == web_api.TASK_STATUS_QUEUED

    def test_restore_history_queued_without_runtime_index_becomes_failed(self, tmp_runtime):
        task_id = "t_queued_no_path"
        history_file = web_api.HISTORY_DIR / f"{task_id}.json"
        history_file.write_text(
            json.dumps(
                {
                    "_schema_version": 2,
                    "id": task_id,
                    "status": web_api.TASK_STATUS_QUEUED,
                    "video_id": "demo",
                    "video_name": "demo.mp4",
                    "created_at": "2024-01-01T00:00:00",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        web_api.tasks.clear()
        web_api._restore_history()

        task = web_api.tasks[task_id]
        assert task.status == web_api.TASK_STATUS_FAILED
        assert task.error == {
            "stage": "web",
            "code": "missing_video_path",
            "message": "重启后缺少视频文件或视频文件不存在，无法重新执行",
        }
        assert web_api.task_queue.empty()

    def test_restore_history_queued_with_missing_video_file_becomes_failed(self, tmp_runtime):
        task_id = "t_queued_missing_file"
        history_file = web_api.HISTORY_DIR / f"{task_id}.json"
        history_file.write_text(
            json.dumps(
                {
                    "_schema_version": 2,
                    "id": task_id,
                    "status": web_api.TASK_STATUS_QUEUED,
                    "video_id": "demo",
                    "video_name": "demo.mp4",
                    "created_at": "2024-01-01T00:00:00",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        non_existent_path = str(tmp_runtime / "uploads" / "non_existent.mp4")
        web_api._save_runtime_index(
            {task_id: {"video_path": non_existent_path, "config_path": ""}}
        )

        web_api.tasks.clear()
        web_api._restore_history()

        task = web_api.tasks[task_id]
        assert task.status == web_api.TASK_STATUS_FAILED
        assert task.error["code"] == "missing_video_path"
        assert web_api.task_queue.empty()

    def test_restore_history_queued_with_existing_video_file_stays_queued(self, tmp_runtime):
        task_id = "t_queued_ok"
        history_file = web_api.HISTORY_DIR / f"{task_id}.json"
        history_file.write_text(
            json.dumps(
                {
                    "_schema_version": 2,
                    "id": task_id,
                    "status": web_api.TASK_STATUS_QUEUED,
                    "video_id": "demo",
                    "video_name": "demo.mp4",
                    "created_at": "2024-01-01T00:00:00",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        video_dir = tmp_runtime / "uploads"
        video_dir.mkdir(parents=True, exist_ok=True)
        video_file = video_dir / "demo.mp4"
        video_file.write_text("dummy content")
        web_api._save_runtime_index(
            {task_id: {"video_path": str(video_file), "config_path": ""}}
        )

        # Clear queue to check if task is queued
        while not web_api.task_queue.empty():
            web_api.task_queue.get_nowait()

        web_api.tasks.clear()
        web_api._restore_history()

        task = web_api.tasks[task_id]
        assert task.status == web_api.TASK_STATUS_QUEUED
        assert not web_api.task_queue.empty()
        assert web_api.task_queue.get_nowait() == task_id

    def test_delete_task_removes_runtime_index_entry(self, client, tmp_runtime):
        video = tmp_runtime / "uploads" / "del.mp4"
        video.write_text("fake video")

        resp = client.post("/api/tasks", data={"video_path": str(video), "video_id": "del"})
        assert resp.status_code == 200
        task_id = resp.json()["id"]
        assert task_id in web_api._load_runtime_index()
        web_api.tasks[task_id].status = web_api.TASK_STATUS_COMPLETED

        resp = client.delete(f"/api/tasks/{task_id}")
        assert resp.status_code == 200

        assert task_id not in web_api._load_runtime_index()

    def test_delete_running_task_is_rejected_and_switch_remains_blocked(self, client):
        task = TaskModel(
            id="running-delete",
            status=web_api.TASK_STATUS_RUNNING,
            created_at="now",
        )
        web_api.tasks[task.id] = task

        response = client.delete(f"/api/tasks/{task.id}")

        assert response.status_code == 409
        assert task.id in web_api.tasks
        assert web_api._configuration_switch_blocked()

    def test_delete_completed_task_removes_transport_traces(self, client, tmp_runtime):
        task = TaskModel(
            id="completed-trace",
            status=web_api.TASK_STATUS_COMPLETED,
            created_at="now",
        )
        web_api.tasks[task.id] = task
        trace_dir = web_api.LLM_TRACES_DIR / task.id
        trace_dir.mkdir(parents=True)
        (trace_dir / "round-0001.json").write_text("{}", encoding="utf-8")

        response = client.delete(f"/api/tasks/{task.id}")

        assert response.status_code == 200
        assert not trace_dir.exists()


class TestConfigEndpoint:
    def test_runtime_dir_redacted(self, client):
        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["runtime_dir"] == "<redacted>"


class TestDecisionModelConfigEndpoints:
    def test_local_snapshot_without_digest_fails_closed(self, tmp_runtime, monkeypatch):
        monkeypatch.setattr(
            web_api,
            "_current_model_snapshot",
            lambda: {
                "backend": "local",
                "provider": "ollama",
                "model": "tensile-qwen35:9b",
                "base_url": "http://localhost:11434/v1",
                "reasoning_effort": "none",
                "digest": None,
            },
        )
        with pytest.raises(web_api.HTTPException) as exc:
            web_api._validated_model_snapshot()
        assert exc.value.status_code == 503

    @pytest.mark.parametrize(
        "snapshot",
        [
            {
                "backend": "unconfigured",
                "provider": "ollama",
                "model": "tensile-qwen35:9b",
                "base_url": "http://localhost:11434/v1",
                "reasoning_effort": "none",
                "digest": "digest",
            },
            {
                "backend": "remote",
                "provider": None,
                "model": "qwen3.7-max",
                "base_url": "https://example.com/v1",
                "reasoning_effort": "none",
                "digest": None,
            },
            {
                "backend": "remote",
                "provider": "dashscope",
                "model": "qwen3.7-max",
                "base_url": None,
                "reasoning_effort": "none",
                "digest": None,
            },
            {
                "backend": "local",
                "provider": "ollama",
                "model": "tensile-qwen35:9b",
                "base_url": "http://localhost:11434/v1",
                "reasoning_effort": "invalid",
                "digest": "digest",
            },
        ],
    )
    def test_incomplete_or_invalid_snapshot_fails_closed(
        self, tmp_runtime, monkeypatch, snapshot
    ):
        monkeypatch.setattr(
            web_api, "_current_model_snapshot", lambda: snapshot.copy()
        )
        with pytest.raises(web_api.HTTPException) as exc:
            web_api._validated_model_snapshot()
        assert exc.value.status_code == 503

    def test_complete_remote_snapshot_is_accepted(self, tmp_runtime, monkeypatch):
        snapshot = {
            "backend": "remote",
            "provider": "dashscope",
            "model": "qwen3.7-max",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "reasoning_effort": "none",
            "digest": None,
        }
        monkeypatch.setattr(
            web_api, "_current_model_snapshot", lambda: snapshot.copy()
        )
        assert web_api._validated_model_snapshot() == snapshot

    def test_single_and_batch_creation_propagate_snapshot_failure(
        self, client, tmp_runtime, monkeypatch
    ):
        def reject_snapshot():
            raise web_api.HTTPException(503, "missing digest")

        monkeypatch.setattr(web_api, "_validated_model_snapshot", reject_snapshot)
        video = tmp_runtime / "uploads" / "missing-digest.mp4"
        video.write_text("fake video")

        single = client.post("/api/tasks", data={"video_path": str(video)})
        batch = client.post(
            "/api/tasks/batch",
            files=[("files", ("missing-digest.mp4", b"fake", "video/mp4"))],
        )

        assert single.status_code == 503
        assert batch.status_code == 503

    def test_lists_local_models(self, client):
        result = {"ok": True, "models": [{"id": "tensile-qwen35:9b", "digest": "abc"}]}
        with patch.object(web_api, "list_local_models", return_value=result):
            response = client.get("/api/config/models?backend=local")
        assert response.status_code == 200
        assert response.json()["models"][0]["id"] == "tensile-qwen35:9b"

    def test_switch_fails_closed_while_task_is_queued(self, client):
        web_api.tasks["queued"] = TaskModel(id="queued", status=web_api.TASK_STATUS_QUEUED, created_at="now")
        response = client.put(
            "/api/config/active",
            json={"backend": "local", "model": "tensile-qwen35:9b", "reasoning_effort": "none"},
        )
        assert response.status_code == 409

    def test_legacy_setup_cannot_bypass_queue_switch_lock(self, client):
        web_api.tasks["running"] = TaskModel(
            id="running", status=web_api.TASK_STATUS_RUNNING, created_at="now"
        )
        with patch.object(
            web_api,
            "list_available_models",
            return_value={"ok": True, "models": ["qwen3.7-max"]},
        ):
            response = client.post(
                "/api/config/setup",
                json={"api_key": "sk-test", "model": "qwen3.7-max", "action": "setup"},
            )
        assert response.status_code == 409

    def test_legacy_model_cannot_bypass_queue_switch_lock(self, client):
        web_api.tasks["queued"] = TaskModel(
            id="queued", status=web_api.TASK_STATUS_QUEUED, created_at="now"
        )
        with patch.object(web_api, "get_api_key", return_value="sk-test"), patch.object(
            web_api,
            "list_available_models",
            return_value={"ok": True, "models": ["qwen3.7-max"]},
        ):
            response = client.put(
                "/api/config/model", json={"model": "qwen3.7-max"}
            )
        assert response.status_code == 409

    def test_switch_persists_after_successful_local_test(self, client):
        local = {"ok": True, "models": [{"id": "tensile-qwen35:9b", "digest": "abc"}]}
        with patch.object(web_api, "list_local_models", return_value=local), patch.object(web_api, "save_active_config") as save:
            response = client.put(
                "/api/config/active",
                json={"backend": "local", "model": "tensile-qwen35:9b", "reasoning_effort": "none"},
            )
        assert response.status_code == 200
        save.assert_called_once_with("local", "tensile-qwen35:9b", reasoning_effort="none")

    def test_trace_endpoint_returns_redacted_runtime_trace(self, client):
        task_id = "trace-task"
        web_api.tasks[task_id] = TaskModel(id=task_id, status=web_api.TASK_STATUS_COMPLETED, created_at="now")
        directory = web_api.LLM_TRACES_DIR / task_id
        directory.mkdir(parents=True)
        (directory / "round-0001.json").write_text(
            json.dumps({"task_id": task_id, "round": 1, "request": {"messages": []}}),
            encoding="utf-8",
        )
        response = client.get(f"/api/tasks/{task_id}/llm-traces")
        assert response.status_code == 200
        assert response.json()[0]["round"] == 1
