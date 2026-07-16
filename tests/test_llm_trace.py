from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

from agent.llm_trace import TransportTraceRecorder, response_to_dict, sanitize_trace


def test_transport_trace_is_complete_and_redacted(tmp_path):
    recorder = TransportTraceRecorder(
        tmp_path,
        "task-1",
        {"backend": "local", "model": "tensile-qwen35:9b", "digest": "abc"},
    )
    response = MagicMock()
    response.model_dump.return_value = {
        "choices": [{"message": {"content": "done", "reasoning_content": "hidden", "tool_calls": []}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2},
    }
    path = recorder.write(
        request={
            "messages": [{"role": "user", "content": "read /private/video.mp4"}],
            "tools": [],
            "max_tokens": 512,
            "authorization": "Bearer secret",
            "payload": "data:video/mp4;base64,AAAA",
        },
        response=response,
        started_at=time.monotonic(),
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    encoded = json.dumps(data, ensure_ascii=False)
    assert data["task_id"] == "task-1"
    assert data["round"] == 1
    assert data["request"]["authorization"] == "<redacted>"
    assert data["request"]["max_tokens"] == 512
    assert data["response"]["usage"]["prompt_tokens"] == 10
    assert data["retry_count"] == 0
    assert "AAAA" not in encoded
    assert "/private/video.mp4" not in encoded
    assert "reasoning_content" not in encoded


def test_transport_trace_includes_reasoning_only_when_enabled(tmp_path):
    recorder = TransportTraceRecorder(tmp_path, "task-2", {"backend": "local"})
    response = MagicMock()
    response.model_dump.return_value = {"choices": [{"message": {"content": "ok", "reasoning_content": "trace"}}]}
    path = recorder.write(
        request={"messages": []},
        response=response,
        started_at=time.monotonic(),
        include_reasoning=True,
    )
    assert "reasoning_content" in path.read_text(encoding="utf-8")


def test_sanitize_trace_redacts_embedded_credentials_and_cross_platform_paths():
    encoded = "A" * 256
    value = sanitize_trace(
        "Authorization: Bearer abc.def; api_key=plain-secret; "
        "read C:\\Users\\Demo User\\clip.mp4 and /private/My Video/clip.mp4\n"
        f"payload={encoded}"
    )
    assert "abc.def" not in value
    assert "plain-secret" not in value
    assert "Demo User" not in value
    assert "My Video" not in value
    assert encoded not in value


def test_response_reasoning_is_removed_recursively_and_repr_is_never_persisted():
    response = MagicMock()
    response.model_dump.return_value = {
        "thinking": "top-secret-thought",
        "nested": [{"reasoning": "nested-secret", "safe": "ok"}],
        "choices": [{"message": {"reasoning_content": "message-secret", "content": "done"}}],
    }
    data = response_to_dict(response, include_reasoning=False)
    encoded = json.dumps(data)
    assert "secret" not in encoded
    assert data["nested"][0]["safe"] == "ok"

    broken = MagicMock()
    broken.model_dump.side_effect = RuntimeError("Bearer should-not-be-in-repr")
    broken.__repr__ = lambda self: "Bearer should-not-be-in-repr"
    fallback = response_to_dict(broken, include_reasoning=False)
    assert fallback == {"serialization_error": "MagicMock"}
