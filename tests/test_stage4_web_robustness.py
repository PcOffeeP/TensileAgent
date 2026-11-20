"""Stage 4B tests: Web event seq/cursor replay and atomic history persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent import web_api


def test_web_events_assign_monotonic_seq_and_support_after_seq_replay(
    tmp_path: Path,
) -> None:
    events_dir = tmp_path / "events"
    history_dir = tmp_path / "history"
    runtime_index = tmp_path / "runtime_index.json"
    task_id = "task-seq-001"
    task = web_api.TaskModel(
        id=task_id,
        status=web_api.TASK_STATUS_RUNNING,
        video_id="v_seq",
        video_name="v_seq.mp4",
        video_path=str(tmp_path / "v_seq.mp4"),
        config_path="agent/config.yaml",
        created_at=web_api._now(),
    )

    with (
        patch.object(web_api, "EVENTS_DIR", events_dir),
        patch.object(web_api, "HISTORY_DIR", history_dir),
        patch.object(web_api, "RUNTIME_INDEX_PATH", runtime_index),
        patch.dict(web_api.tasks, {task_id: task}, clear=False),
    ):
        web_api._event_seq.pop(task_id, None)
        web_api._save_task(task)
        assert not list(history_dir.glob("*.tmp"))
        assert not list(tmp_path.glob("*.tmp"))
        saved = json.loads((history_dir / f"{task_id}.json").read_text("utf-8"))
        assert "video_path" not in saved
        assert saved["_schema_version"] == 2

        web_api._append_event(task_id, {"task_id": task_id, "event": "task_started", "data": {}})
        web_api._append_event(task_id, {"task_id": task_id, "event": "round_started", "data": {"round": 0}})
        web_api._append_event(task_id, {"task_id": task_id, "event": "task_completed", "data": {}})

        client = TestClient(web_api.app)
        all_events = client.get(f"/api/tasks/{task_id}/events/replay").json()
        assert [e["seq"] for e in all_events] == [1, 2, 3]

        incremental = client.get(
            f"/api/tasks/{task_id}/events/replay", params={"after_seq": 1}
        ).json()
        assert [e["seq"] for e in incremental] == [2, 3]
