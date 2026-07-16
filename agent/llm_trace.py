"""Auditable, redacted transport traces for decision-model calls."""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any


_SECRET_RE = re.compile(
    r"(?i)^(api[_-]?key|authorization|proxy[_-]?authorization|access[_-]?token|refresh[_-]?token|base64)$"
)
_DATA_URI_RE = re.compile(r"data:[^\s;]+;base64,[A-Za-z0-9+/=]+")
_LONG_BASE64_RE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{128,}={0,2}(?![A-Za-z0-9+/])")
_API_KEY_RE = re.compile(r"sk-[A-Za-z0-9_-]+")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_CREDENTIAL_TEXT_RE = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|access[_ -]?token|refresh[_ -]?token)\s*[:=]\s*[^\s,;]+"
)
_WINDOWS_PATH_RE = re.compile(r"(?i)\b[A-Z]:\\[^\r\n]+")
_ABS_PATH_RE = re.compile(r"(?<![:/\w])/(?!/)[^\r\n]+")
_REASONING_KEYS = {"reasoning", "reasoning_content", "thinking"}


def sanitize_trace(value: Any, key: str | None = None) -> Any:
    """Remove credentials, media payloads and absolute paths recursively."""
    if key and _SECRET_RE.search(key):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): sanitize_trace(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_trace(item, key) for item in value]
    if isinstance(value, str):
        value = _DATA_URI_RE.sub("<data:redacted>", value)
        value = _LONG_BASE64_RE.sub("<base64:redacted>", value)
        value = _API_KEY_RE.sub("<api_key:redacted>", value)
        value = _BEARER_RE.sub("Bearer <redacted>", value)
        value = _CREDENTIAL_TEXT_RE.sub(lambda match: f"{match.group(1)}=<redacted>", value)
        value = _WINDOWS_PATH_RE.sub("<path:redacted>", value)
        return _ABS_PATH_RE.sub("<path:redacted>", value)
    return value


def _drop_reasoning(value: Any) -> Any:
    """Remove reasoning-like fields recursively from arbitrary responses."""
    if isinstance(value, dict):
        return {
            key: _drop_reasoning(item)
            for key, item in value.items()
            if str(key).lower() not in _REASONING_KEYS
        }
    if isinstance(value, list):
        return [_drop_reasoning(item) for item in value]
    return value


def response_to_dict(response: Any, *, include_reasoning: bool) -> dict[str, Any]:
    try:
        data = response.model_dump(mode="json")
    except TypeError:
        try:
            data = response.model_dump()
        except Exception:
            data = {"serialization_error": type(response).__name__}
    except Exception:
        # ``repr(response)`` may contain credentials or hidden reasoning in an
        # unknown vendor format.  Preserve only the type on serialization
        # failure and fail privacy-closed.
        data = {"serialization_error": type(response).__name__}
    if not isinstance(data, dict):
        data = {"value": data}
    if not include_reasoning:
        data = _drop_reasoning(data)
    return data


class TransportTraceRecorder:
    """Persist one sanitized JSON file per decision-model request."""

    def __init__(self, root: str | Path, task_id: str, model_snapshot: dict[str, Any]) -> None:
        self.directory = Path(root) / task_id
        self.task_id = task_id
        self.model_snapshot = sanitize_trace(model_snapshot)
        self._counter = 0
        self._lock = threading.Lock()

    def write(
        self,
        *,
        request: dict[str, Any],
        response: Any | None,
        started_at: float,
        error: Exception | None = None,
        include_reasoning: bool = False,
    ) -> Path:
        with self._lock:
            self._counter += 1
            round_number = self._counter
        payload = {
            "schema_version": 1,
            "task_id": self.task_id,
            "round": round_number,
            "request_id": str(uuid.uuid4()),
            "model": self.model_snapshot,
            "request": sanitize_trace(request),
            "response": sanitize_trace(response_to_dict(response, include_reasoning=include_reasoning)) if response is not None else None,
            "elapsed_seconds": round(time.monotonic() - started_at, 6),
            # The decision clients disable SDK-level retries so this value is
            # exact rather than an estimate hidden inside the SDK.
            "retry_count": 0,
            "error": None if error is None else {"type": type(error).__name__, "message": sanitize_trace(str(error))},
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"round-{round_number:04d}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
