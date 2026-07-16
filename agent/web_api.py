"""Agent 本地 Web 工作台 API"""
import argparse
import asyncio
import csv
import io
import json
import os
import shutil
import re
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import uvicorn
import yaml
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agent.runner import run_one
from agent.config_util import (
    get_active_model_config,
    get_active_backend,
    get_api_key,
    get_configured_model,
    get_local_model_digest,
    has_session_overrides,
    list_local_models,
    list_available_models,
    load_config,
    save_api_key,
    save_active_config,
    save_model,
    save_remote_model,
    set_session_overrides,
)

# ── 路径常量 ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / "data" / "08_runtime" / "web_workbench"
UPLOADS_DIR = RUNTIME_DIR / "uploads"
HISTORY_DIR = RUNTIME_DIR / "history"
EVENTS_DIR = RUNTIME_DIR / "events"
LLM_TRACES_DIR = PROJECT_ROOT / "data" / "08_runtime" / "llm_traces"
RUNTIME_INDEX_PATH = RUNTIME_DIR / "private_runtime_index.json"
CONFIG_PATH = PROJECT_ROOT / "agent" / "config.yaml"

# ── 任务模型 ──────────────────────────────────────────────
TASK_STATUS_QUEUED = "queued"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_FAILED = "failed"


class TaskModel(BaseModel):
    id: str
    status: str = TASK_STATUS_QUEUED
    video_id: str = ""
    video_name: str = ""
    video_path: str = ""
    config_path: str = ""
    question: str = "请完整分析这段拉伸试验视频"
    created_at: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    result: Optional[dict] = None
    response: Optional[dict] = None
    error: Optional[dict] = None
    event_summary: Optional[dict] = None
    decision_model: Optional[dict] = None


class PublicTask(BaseModel):
    """对外公开的任务视图（不包含内部绝对路径）"""

    id: str
    status: str
    video_id: str
    video_name: str = ""
    question: str = "请完整分析这段拉伸试验视频"
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    result: Optional[dict] = None
    response: Optional[dict] = None
    error: Optional[dict] = None
    event_summary: Optional[dict] = None
    decision_model: Optional[dict] = None


# ── 全局状态 ──────────────────────────────────────────────
tasks: dict[str, TaskModel] = {}
task_queue: asyncio.Queue[str] = asyncio.Queue()
_queue_worker_task: Optional[asyncio.Task] = None
sse_connections: dict[str, list[asyncio.Queue]] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Initialize runtime state and own the queue worker lifecycle."""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    _restore_history()
    global _queue_worker_task
    _queue_worker_task = asyncio.create_task(_queue_worker())
    try:
        yield
    finally:
        if _queue_worker_task is not None:
            _queue_worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await _queue_worker_task
        _queue_worker_task = None


# ── FastAPI 应用 ─────────────────────────────────────────
app = FastAPI(title="Agent Web Workbench API", version="1.0.0", lifespan=lifespan)


# ── 脱敏规则 ──────────────────────────────────────────────
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(base64|token|api_key|video_path|model_video_path|clip_path|temp_path|config_path)"
)
# 识别嵌入在文本中的 URL（避免被脱敏）、POSIX 绝对路径 /... 与 Windows 绝对路径 C:\...
_PATH_VALUE_RE = re.compile(
    r"(?P<url>[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/]*(?:/[^\s\n\r]*)?)"
    r"|(?P<win>[A-Za-z]:[\\/][^/\\:\n\r\s]*(?:[\\/][^/\\:\n\r\s]+)*)"
    r"|(?P<posix>(?:/[^/\\:\n\r\s]+)+)"
)
_RUNTIME_CLIP_CONFIG_RE = re.compile(r"(?i)(runtime|clip|config)")
_DATA_URI_RE = re.compile(r"data:[^\s;]+;base64,[A-Za-z0-9+/=]+")
_BEARER_RE = re.compile(r"Bearer\s+\S+")
_API_KEY_RE = re.compile(r"sk-\S+")


# ── 工具函数 ──────────────────────────────────────────────
def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _task_path(task_id: str) -> Path:
    return HISTORY_DIR / f"{task_id}.json"


def _events_path(task_id: str) -> Path:
    return EVENTS_DIR / f"{task_id}.jsonl"


def _load_runtime_index() -> dict[str, dict]:
    if not RUNTIME_INDEX_PATH.exists():
        return {}
    try:
        data = json.loads(RUNTIME_INDEX_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _save_runtime_index(index: dict):
    RUNTIME_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_INDEX_PATH.write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _update_runtime_index(task: TaskModel):
    index = _load_runtime_index()
    index[task.id] = {"video_path": task.video_path, "config_path": task.config_path}
    _save_runtime_index(index)


def _remove_runtime_index_entry(task_id: str):
    index = _load_runtime_index()
    if task_id in index:
        del index[task_id]
        _save_runtime_index(index)


def _save_task(task: TaskModel):
    """持久化公开任务视图到历史 JSON，并把内部路径保存到私有 runtime index。"""
    public = PublicTask(
        id=task.id,
        status=task.status,
        video_id=task.video_id,
        video_name=task.video_name,
        question=task.question,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        result=_sanitize_event_data(task.result),
        response=_sanitize_event_data(task.response),
        error=_sanitize_event_data(task.error),
        event_summary=_sanitize_event_data(task.event_summary),
        decision_model=_sanitize_event_data(task.decision_model),
    )
    d = public.model_dump()
    d["_schema_version"] = 2
    _task_path(task.id).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    _update_runtime_index(task)


def _restore_history():
    """服务启动时从磁盘恢复历史任务。

    - 公开历史 JSON 仅保存 ``PublicTask`` 字段。
    - 内部 ``video_path`` / ``config_path`` 从私有 runtime index 回填。
    - 旧格式（含 ``video_path`` / ``config_path`` 或 ``_schema_version == 1``）
      自动迁移：构造 ``TaskModel``，写入 runtime index，并重写为公开格式。
    """
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    runtime_index = _load_runtime_index()

    for f in sorted(HISTORY_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue

        schema_version = data.get("_schema_version")
        is_old_format = (
            schema_version == 1
            or "video_path" in data
            or "config_path" in data
        )

        if is_old_format:
            task = TaskModel(**data)
            runtime_index[task.id] = {
                "video_path": task.video_path,
                "config_path": task.config_path,
            }
            _save_runtime_index(runtime_index)
            _save_task(task)
        else:
            public_fields = {k: data[k] for k in PublicTask.model_fields if k in data}
            try:
                public = PublicTask(**public_fields)
            except Exception:
                continue
            paths = runtime_index.get(public.id, {})
            task = TaskModel(
                id=public.id,
                status=public.status,
                video_id=public.video_id,
                video_name=public.video_name,
                question=public.question,
                created_at=public.created_at,
                started_at=public.started_at,
                finished_at=public.finished_at,
                result=public.result,
                response=public.response,
                error=public.error,
                event_summary=public.event_summary,
                decision_model=public.decision_model,
                video_path=paths.get("video_path", ""),
                config_path=paths.get("config_path", ""),
            )

        tasks[task.id] = task

        if task.status == TASK_STATUS_RUNNING:
            task.status = TASK_STATUS_FAILED
            task.error = {
                "stage": "web",
                "code": "restart",
                "message": "任务在服务器重启时中断",
            }
            _save_task(task)
        elif task.status == TASK_STATUS_QUEUED:
            if not task.video_path or not Path(task.video_path).exists():
                task.status = TASK_STATUS_FAILED
                task.error = {
                    "stage": "web",
                    "code": "missing_video_path",
                    "message": "重启后缺少视频文件或视频文件不存在，无法重新执行",
                }
                _save_task(task)
            else:
                try:
                    task_queue.put_nowait(task.id)
                except Exception:
                    pass
        elif task.status not in (TASK_STATUS_COMPLETED, TASK_STATUS_FAILED):
            task.status = TASK_STATUS_FAILED
            task.error = {
                "stage": "web",
                "code": "unknown_status",
                "message": f"未识别的任务状态: {task.status}",
            }
            _save_task(task)


def _basename(path_str: str) -> str:
    """跨平台取路径 basename（兼容 POSIX 与 Windows 风格分隔符）"""
    return path_str.replace("\\", "/").split("/")[-1]


def _sanitize_string(value: str, key: str | None = None) -> str:
    """对单个字符串进行 value-level 脱敏。

    处理顺序：
    - data URI（``data:...;base64,...``）→ ``<data:redacted>``；
    - Bearer token（``Bearer ...``）→ ``<token:redacted>``；
    - API key（``sk-...``）→ ``<api_key:redacted>``；
    - 嵌入的 POSIX/Windows 绝对路径：
      - key 含 runtime/clip/config → ``<redacted>``；
      - key 含 message → ``<path:redacted>``；
      - 其他 → basename。
    """
    value = _DATA_URI_RE.sub("<data:redacted>", value)
    value = _BEARER_RE.sub("<token:redacted>", value)
    value = _API_KEY_RE.sub("<api_key:redacted>", value)

    def _replace_path(match: re.Match) -> str:
        if match.group("url"):
            return match.group("url")
        path = match.group(0)
        if key is not None:
            lower_key = key.lower()
            if _RUNTIME_CLIP_CONFIG_RE.search(lower_key):
                return "<redacted>"
            if "message" in lower_key:
                return "<path:redacted>"
        return _basename(path)

    return _PATH_VALUE_RE.sub(_replace_path, value)


def _sanitize_event_data(data: Any, key: str | None = None) -> Any:
    """递归过滤敏感字段与嵌入字符串中的敏感值。

    规则：
    - 键名命中敏感正则时，值整体替换为 ``<redacted>``；
    - 字符串值按 ``_sanitize_string`` 进行 value-level 脱敏；
    - 路径替换会继承所在 key 的上下文（runtime/clip/config、message、其他）。
    """
    if isinstance(data, dict):
        safe: dict[str, Any] = {}
        for k, value in data.items():
            if _SENSITIVE_KEY_RE.search(k):
                safe[k] = "<redacted>"
                continue
            if isinstance(value, str):
                safe[k] = _sanitize_string(value, k)
                continue
            safe[k] = _sanitize_event_data(value, k)
        return safe
    if isinstance(data, list):
        return [_sanitize_event_data(item, key) for item in data]
    if isinstance(data, str):
        return _sanitize_string(data, key)
    return data


def _append_event(task_id: str, event: dict):
    """追加事件到 JSONL 文件并推送 SSE（持久化前会先脱敏）"""
    path = _events_path(task_id)
    safe_event = _sanitize_event_data(event)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(safe_event, ensure_ascii=False) + "\n")
    # 推送 SSE
    if task_id in sse_connections:
        dead = []
        for q in sse_connections[task_id]:
            try:
                q.put_nowait(safe_event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            sse_connections[task_id].remove(q)


def _event_callback_factory(task_id: str):
    """创建 runner 事件回调。Agent 原始事件使用 ``event_type`` 字段。"""
    def callback(event_data: dict):
        event_type = event_data.get("event_type") or event_data.get("event") or "unknown"
        event = {
            "task_id": task_id,
            "event": event_type,
            "data": event_data,
            "timestamp": _now(),
        }
        _append_event(task_id, event)
    return callback


# ── SSE 事件流端点 ───────────────────────────────────────
@app.get("/api/tasks/{task_id}/events")
async def task_events(task_id: str):
    """SSE 实时事件流，只推送实时事件和 ping，不回放历史事件。"""
    if task_id not in tasks:
        raise HTTPException(404, "task not found")

    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    if task_id not in sse_connections:
        sse_connections[task_id] = []
    sse_connections[task_id].append(queue)

    async def event_generator():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield {"data": json.dumps(event)}
                except asyncio.TimeoutError:
                    yield {"data": json.dumps({"event": "ping", "timestamp": _now()})}
        except asyncio.CancelledError:
            pass
        finally:
            if task_id in sse_connections:
                sse_connections[task_id] = [q for q in sse_connections[task_id] if q is not queue]

    return EventSourceResponse(event_generator())


# ── 队列 worker ──────────────────────────────────────────
async def _queue_worker():
    """单 worker 顺序队列"""
    while True:
        task_id = await task_queue.get()
        task = tasks.get(task_id)
        if not task:
            continue

        task.status = TASK_STATUS_RUNNING
        task.started_at = _now()
        _save_task(task)

        _append_event(task_id, {
            "task_id": task_id,
            "event": "task_started",
            "data": {"video_id": task.video_id},
            "timestamp": _now(),
        })

        try:
            config_path = task.config_path or str(CONFIG_PATH)
            # run_one 是同步的，在线程中运行
            loop = asyncio.get_event_loop()
            runner_result = await loop.run_in_executor(
                None,
                lambda: run_one(
                    video_path=task.video_path,
                    config_path=config_path,
                    video_id=task.video_id,
                    event_callback=_event_callback_factory(task_id),
                    question=task.question,
                    agent_config_snapshot=task.decision_model,
                    trace_task_id=task.id,
                    work_dir=PROJECT_ROOT,
                )
            )

            # 统一解包 RunnerResult 并映射任务状态/结果
            _apply_runner_result_to_task(task, runner_result)
        except Exception as e:
            task.status = TASK_STATUS_FAILED
            task.error = {"stage": "runner", "code": type(e).__name__, "message": str(e)}
            _append_event(task_id, {
                "task_id": task_id,
                "event": "task_failed",
                "data": _sanitize_event_data(task.error),
                "timestamp": _now(),
            })
        finally:
            task.finished_at = _now()
            _save_task(task)


def _normalize_result(result: Any) -> dict:
    """将 runner 结果转为公共 ``FinalOutput`` 格式。

    优先识别 ``ok/result/error`` 新契约；否则保留旧字段兜底并标记迁移兼容。
    """
    if not result:
        return {"status": "unrecognized"}
    if isinstance(result, BaseModel):
        result = result.model_dump()
    if not isinstance(result, dict):
        return {"status": "unrecognized"}

    ok = result.get("ok")
    if ok is True:
        res = result.get("result") or {}
        return {
            k: v
            for k, v in {
                "video_id": res.get("video_id", result.get("video_id", "")),
                "status": res.get("status", "unrecognized"),
                "time_range": res.get("time_range"),
                "fracture_type": res.get("fracture_type"),
                "location": res.get("location"),
                "confidence": res.get("confidence"),
                "visual_evidence": res.get("visual_evidence"),
                "unrecognized_reason": res.get("unrecognized_reason"),
                "rounds": result.get("rounds", result.get("total_rounds")),
            }.items()
            if v is not None or k in ("video_id", "status")
        }

    if ok is False:
        error = result.get("error") or {}
        return {"status": "failed", **error}

    # 旧字段兜底（迁移兼容）
    output = result.get("output") or result.get("final_output") or {}
    normalized = {
        "status": result.get("status", result.get("final_status", "unrecognized")),
        "video_id": result.get("video_id", ""),
        "fracture_type": output.get("type", result.get("fracture_type")),
        "location": output.get("location", result.get("location")),
        "confidence": output.get("confidence", result.get("confidence")),
        "visual_evidence": output.get("visual_evidence", result.get("visual_evidence")),
        "time_range": output.get("fracture_between", result.get("time_range")),
        "unrecognized_reason": result.get("unrecognized_reason"),
        "rounds": result.get("rounds", result.get("total_rounds")),
        "_migration_compat": True,
    }
    start_time = result.get("start_time")
    end_time = result.get("end_time")
    if start_time is not None and end_time is not None and normalized.get("time_range") is None:
        normalized["time_range"] = [start_time, end_time]
    return {
        k: v
        for k, v in normalized.items()
        if v is not None or k in ("status", "video_id", "_migration_compat")
    }


def _apply_runner_result_to_task(task: TaskModel, runner_result: Any):
    """共享的 RunnerResult 解包逻辑：单任务与 batch 共用。"""
    if isinstance(runner_result, BaseModel):
        runner_result = runner_result.model_dump()

    if isinstance(runner_result, dict) and runner_result.get("ok") is False:
        task.status = TASK_STATUS_FAILED
        task.result = None
        error = runner_result.get("error")
        if isinstance(error, dict):
            task.error = {
                "stage": error.get("stage", "runner"),
                "code": error.get("code", "unknown_error"),
                "message": error.get("message", str(error)),
            }
        else:
            task.error = {
                "stage": "runner",
                "code": "unknown_error",
                "message": str(error) if error is not None else "unknown runner error",
            }
        _append_event(task.id, {
            "task_id": task.id,
            "event": "task_failed",
            "data": task.error,
            "timestamp": _now(),
        })
        return

    task.status = TASK_STATUS_COMPLETED
    task.result = _normalize_result(runner_result)
    if isinstance(runner_result, dict):
        task.response = _sanitize_event_data(runner_result.get("response"))
    _append_event(task.id, {
        "task_id": task.id,
        "event": "task_completed",
        "data": {"result": task.result, "response": task.response},
        "timestamp": _now(),
    })


def _to_public_task(task: TaskModel) -> dict:
    """将内部 ``TaskModel`` 转换为对外 ``PublicTask``。"""
    return PublicTask(
        id=task.id,
        status=task.status,
        video_id=task.video_id,
        video_name=task.video_name,
        question=task.question,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        result=_sanitize_event_data(task.result),
        response=_sanitize_event_data(task.response),
        error=_sanitize_event_data(task.error),
        event_summary=_sanitize_event_data(task.event_summary),
        decision_model=_sanitize_event_data(task.decision_model),
    ).model_dump()


def _current_model_snapshot() -> dict[str, Any]:
    snapshot = get_active_model_config()
    if snapshot.get("backend") == "local" and snapshot.get("model"):
        snapshot["digest"] = get_local_model_digest(
            snapshot["model"], snapshot.get("base_url") or "http://localhost:11434/v1"
        )
    else:
        snapshot["digest"] = None
    return snapshot


def _validated_model_snapshot() -> dict[str, Any]:
    """Return a complete task snapshot or fail before queueing the task."""
    snapshot = _current_model_snapshot()
    backend = snapshot.get("backend")
    if backend not in {"local", "remote"}:
        raise HTTPException(503, "决策模型 backend 配置无效")
    missing = [
        field
        for field in ("provider", "model", "base_url", "reasoning_effort")
        if not isinstance(snapshot.get(field), str) or not snapshot[field].strip()
    ]
    if missing:
        raise HTTPException(503, f"决策模型快照字段不完整: {', '.join(missing)}")
    if snapshot["reasoning_effort"] not in {"none", "low", "medium", "high"}:
        raise HTTPException(503, "决策模型 reasoning_effort 配置无效")
    if backend == "local" and not snapshot.get("digest"):
        raise HTTPException(
            503,
            "本地决策模型不可用、未安装或缺少 digest；请启动 Ollama 并确认模型后重试",
        )
    return snapshot


def _configuration_switch_blocked() -> bool:
    return any(task.status in {TASK_STATUS_QUEUED, TASK_STATUS_RUNNING} for task in tasks.values())


# ── API 端点 ─────────────────────────────────────────────
@app.get("/api/health")
async def health():
    """健康检查"""
    return {"ok": True, "status": "running", "tasks": len(tasks), "queue_size": task_queue.qsize()}


@app.get("/api/config")
async def get_config():
    """返回当前配置摘要（不包含密钥）"""
    cfg = load_config()
    active_backend = get_active_backend()
    agent_cfg = cfg.get("agent", {})
    if active_backend == "remote":
        active_model = agent_cfg.get("remote", {}).get("model")
    elif active_backend == "local":
        active_model = agent_cfg.get("local", {}).get("model")
    else:
        active_model = None
    local_cfg = agent_cfg.get("local", {})
    local_status = list_local_models(local_cfg.get("base_url", "http://localhost:11434/v1"))
    active_digest = None
    if active_backend == "local" and active_model:
        active_digest = next(
            (item.get("digest") for item in local_status.get("models", []) if item.get("id") == active_model),
            None,
        )
    return {
        "active_backend": active_backend,
        "active_model": active_model,
        "mock": cfg.get("mock", False),
        "runtime_dir": "<redacted>",
        "max_rounds": agent_cfg.get("max_rounds", 10),
        "active_digest": active_digest,
        "ollama_ok": local_status.get("ok", False),
        "reasoning_effort": local_cfg.get("reasoning_effort", "none"),
        "switch_allowed": not _configuration_switch_blocked() and not has_session_overrides(),
        "session_override": has_session_overrides(),
    }


@app.post("/api/tasks")
async def create_task(
    file: Optional[UploadFile] = File(None),
    video_path: Optional[str] = Form(None),
    video_id: Optional[str] = Form(None),
    config_path: Optional[str] = Form(None),
    question: Optional[str] = Form(None),
):
    """创建分析任务：支持上传文件、本地路径"""
    if not file and not video_path:
        raise HTTPException(400, "必须提供视频文件或视频路径")

    decision_model = _validated_model_snapshot()
    task_id = str(uuid.uuid4())
    vid = video_id or f"task_{task_id[:8]}"

    if file:
        # 保存上传文件
        video_name = Path(file.filename).name
        upload_path = UPLOADS_DIR / f"{task_id}_{video_name}"
        with upload_path.open("wb") as f:
            f.write(await file.read())
        vpath = str(upload_path)
    else:
        video_name = Path(video_path).name
        vpath = str(Path(video_path).resolve())
        if not os.path.isfile(vpath):
            raise HTTPException(400, f"视频文件不存在: {vpath}")

    task = TaskModel(
        id=task_id,
        video_id=vid,
        video_name=video_name,
        video_path=vpath,
        config_path=config_path or "",
        question=(question or "请完整分析这段拉伸试验视频").strip(),
        created_at=_now(),
        decision_model=decision_model,
    )
    tasks[task_id] = task
    _save_task(task)

    # 入队
    await task_queue.put(task_id)

    _append_event(task_id, {
        "task_id": task_id,
        "event": "task_created",
        "data": {"video_id": vid, "video_path": vpath},
        "timestamp": _now(),
    })

    return {"task_id": task_id, **_to_public_task(task)}


@app.get("/api/tasks")
async def list_tasks(limit: int = Query(50, ge=1, le=200)):
    """任务列表，按创建时间倒序"""
    sorted_tasks = sorted(tasks.values(), key=lambda t: t.created_at, reverse=True)
    return [_to_public_task(t) for t in sorted_tasks[:limit]]


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    if task_id not in tasks:
        raise HTTPException(404, "task not found")
    return _to_public_task(tasks[task_id])


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """删除任务及其数据"""
    if task_id not in tasks:
        raise HTTPException(404, "task not found")
    if tasks[task_id].status in {TASK_STATUS_QUEUED, TASK_STATUS_RUNNING}:
        raise HTTPException(409, "排队或运行中任务不能删除")
    # 清理文件
    for p in [HISTORY_DIR / f"{task_id}.json", EVENTS_DIR / f"{task_id}.jsonl"]:
        if p.exists():
            p.unlink()
    # 清理上传文件
    task = tasks[task_id]
    if task.video_path and task.video_path.startswith(str(UPLOADS_DIR)):
        p = Path(task.video_path)
        if p.exists():
            p.unlink()
    _remove_runtime_index_entry(task_id)
    trace_dir = LLM_TRACES_DIR / task_id
    if trace_dir.exists():
        shutil.rmtree(trace_dir)
    del tasks[task_id]
    return {"ok": True}


@app.get("/api/tasks/{task_id}/events/replay")
async def replay_events(task_id: str):
    """回放历史事件，结构与 SSE 输出一致并脱敏"""
    if task_id not in tasks:
        raise HTTPException(404, "task not found")
    path = _events_path(task_id)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    events = []
    for line in lines:
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        ev = _sanitize_event_data(ev)
        if not isinstance(ev, dict):
            continue
        if "event" not in ev and isinstance(ev.get("data"), dict):
            ev["event"] = ev["data"].get("event_type") or ev["data"].get("event") or "unknown"
        events.append(ev)
    return events


def _load_llm_traces(task_id: str) -> list[dict[str, Any]]:
    trace_dir = LLM_TRACES_DIR / task_id
    traces: list[dict[str, Any]] = []
    if not trace_dir.exists():
        return traces
    for path in sorted(trace_dir.glob("round-*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            traces.append(_sanitize_event_data(value))
    return traces


@app.get("/api/tasks/{task_id}/llm-traces")
async def get_llm_traces(task_id: str):
    if task_id not in tasks:
        raise HTTPException(404, "task not found")
    return _load_llm_traces(task_id)


@app.get("/api/tasks/{task_id}/llm-traces/export")
async def export_llm_traces(task_id: str):
    if task_id not in tasks:
        raise HTTPException(404, "task not found")
    return JSONResponse(
        _load_llm_traces(task_id),
        headers={"Content-Disposition": f'attachment; filename="{task_id}-llm-traces.json"'},
    )


@app.get("/api/tasks/{task_id}/export")
async def export_result(task_id: str, fmt: str = Query("json", pattern="^(json|jsonl|csv)$")):
    """导出分析结果"""
    if task_id not in tasks:
        raise HTTPException(404, "task not found")
    task = tasks[task_id]
    result = _sanitize_event_data(task.result or {})
    error = _sanitize_event_data(task.error or {})

    if fmt == "json":
        return JSONResponse(result)
    elif fmt == "jsonl":
        lines = [json.dumps(result, ensure_ascii=False)]
        return Response("\n".join(lines), media_type="application/x-ndjson")
    else:  # csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "video_id", "status", "time_range_start", "time_range_end",
            "fracture_type", "location", "confidence", "unrecognized_reason",
            "rounds", "error_stage", "error_code", "error_message",
        ])
        time_range = result.get("time_range") or [None, None]
        if not isinstance(time_range, (list, tuple)) or len(time_range) != 2:
            time_range = [None, None]
        csv_status = task.status
        if task.status == TASK_STATUS_COMPLETED:
            csv_status = result.get("status") or TASK_STATUS_COMPLETED
        elif task.status == TASK_STATUS_FAILED:
            csv_status = TASK_STATUS_FAILED
        writer.writerow([
            result.get("video_id", task.video_id),
            csv_status,
            time_range[0] if time_range[0] is not None else "",
            time_range[1] if time_range[1] is not None else "",
            result.get("fracture_type") if result.get("fracture_type") is not None else "",
            result.get("location") if result.get("location") is not None else "",
            result.get("confidence") if result.get("confidence") is not None else "",
            result.get("unrecognized_reason") if result.get("unrecognized_reason") is not None else "",
            result.get("rounds") if result.get("rounds") is not None else 0,
            error.get("stage") if error.get("stage") is not None else "",
            error.get("code") if error.get("code") is not None else "",
            error.get("message") if error.get("message") is not None else "",
        ])
        return Response(output.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=result.csv"})


@app.post("/api/tasks/batch")
async def create_batch_tasks(
    files: list[UploadFile] = File(...),
    config_path: Optional[str] = Form(None),
    question: Optional[str] = Form(None),
):
    """批量上传并创建任务（每个任务同样进入队列，由统一 worker 处理）"""
    decision_model = _validated_model_snapshot()
    results = []
    for f in files:
        task_id = str(uuid.uuid4())
        video_name = Path(f.filename).name
        upload_path = UPLOADS_DIR / f"{task_id}_{video_name}"
        with upload_path.open("wb") as wf:
            wf.write(await f.read())
        vid = Path(f.filename).stem
        task = TaskModel(
            id=task_id,
            video_id=vid,
            video_name=video_name,
            video_path=str(upload_path),
            config_path=config_path or "",
            question=(question or "请完整分析这段拉伸试验视频").strip(),
            created_at=_now(),
            decision_model=decision_model.copy(),
        )
        tasks[task_id] = task
        _save_task(task)
        await task_queue.put(task_id)
        _append_event(task_id, {
            "task_id": task_id,
            "event": "task_created",
            "data": {"video_id": vid, "video_path": str(upload_path)},
            "timestamp": _now(),
        })
        results.append({"task_id": task_id, **_to_public_task(task)})
    return {"tasks": results}


@app.get("/api/config/status")
async def get_config_status():
    """Check backend configuration status.

    Returns active_backend plus remote/local dimensions without exposing
    the full API key.
    """
    active_backend = get_active_backend()
    api_key = get_api_key()
    remote_model = get_configured_model()

    config = load_config()
    agent_cfg = config.get("agent", {})
    local_cfg = agent_cfg.get("local", {})
    local_model = local_cfg.get("model")
    local_result = list_local_models(local_cfg.get("base_url", "http://localhost:11434/v1"))
    installed_ids = [item.get("id") for item in local_result.get("models", [])]

    # 按当前 backend 判断是否已配置
    if active_backend == "remote":
        configured = bool(api_key) and bool(remote_model)
    elif active_backend == "local":
        configured = bool(local_result.get("ok")) and local_model in installed_ids
    else:
        configured = False

    masked_key = None
    if api_key and len(api_key) > 8:
        masked_key = api_key[:6] + "*" * (len(api_key) - 10) + api_key[-4:]

    return {
        "active_backend": active_backend,
        "configured": configured,
        "remote": {
            "has_api_key": bool(api_key),
            "current_model": remote_model,
            "api_key_masked": masked_key,
        },
        "local": {
            "current_model": local_model,
            "service_ok": local_result.get("ok", False),
            "installed": local_model in installed_ids,
            "digest": next(
                (item.get("digest") for item in local_result.get("models", []) if item.get("id") == local_model),
                None,
            ),
            "warning": local_result.get("warning"),
            "reasoning_effort": local_cfg.get("reasoning_effort", "none"),
        },
        "switch_allowed": not _configuration_switch_blocked() and not has_session_overrides(),
        "session_override": has_session_overrides(),
    }


@app.get("/api/config/models")
async def get_config_models(backend: str = Query(..., pattern="^(local|remote)$")):
    config = load_config()
    if backend == "local":
        local_cfg = config.get("agent", {}).get("local", {})
        result = list_local_models(local_cfg.get("base_url", "http://localhost:11434/v1"))
        return result
    remote_cfg = config.get("agent", {}).get("remote", {})
    result = list_available_models(
        base_url=remote_cfg.get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
        api_key=get_api_key(),
    )
    return {**result, "models": [{"id": model} for model in result.get("models", [])]}


@app.post("/api/config/test")
async def test_config_backend(body: dict):
    backend = str(body.get("backend", "")).strip()
    model = str(body.get("model", "")).strip()
    config = load_config()
    if backend == "local":
        local_cfg = config.get("agent", {}).get("local", {})
        result = list_local_models(local_cfg.get("base_url", "http://localhost:11434/v1"))
        installed = {item.get("id") for item in result.get("models", [])}
        if not result.get("ok"):
            raise HTTPException(503, result.get("warning", "Ollama 不可用"))
        if model not in installed:
            raise HTTPException(400, f"本地模型未安装: {model}")
        return {"ok": True, "backend": backend, "model": model}
    if backend == "remote":
        if not get_api_key():
            raise HTTPException(400, "远程后端尚未配置 API Key")
        result = list_available_models(
            base_url=config.get("agent", {}).get("remote", {}).get("base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            api_key=get_api_key(),
        )
        if not result.get("ok"):
            raise HTTPException(503, result.get("warning", "远程后端不可用"))
        return {"ok": True, "backend": backend, "model": model}
    raise HTTPException(400, "backend 必须为 local 或 remote")


@app.put("/api/config/active")
async def update_active_config(body: dict):
    if has_session_overrides():
        raise HTTPException(409, "当前进程由启动参数锁定模型；请重启时移除覆盖参数")
    if _configuration_switch_blocked():
        raise HTTPException(409, "存在运行中或排队任务，暂不能切换决策模型")
    backend = str(body.get("backend", "")).strip()
    model = str(body.get("model", "")).strip()
    reasoning_effort = str(body.get("reasoning_effort", "none")).strip()
    await test_config_backend({"backend": backend, "model": model})
    try:
        save_active_config(backend, model, reasoning_effort=reasoning_effort)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "backend": backend, "model": model, "reasoning_effort": reasoning_effort}


@app.post("/api/config/setup")
async def setup_config(body: dict):
    """Save API key and model, with best-effort connection test.

    Request body:
    {
        "api_key": "sk-...",
        "model": "qwen-max",
        "action": "setup"   // optional: "setup" (default) or "test"
    }

    - /models query is best-effort (used for recommendations, not as a blocker).
    - Only an invalid API key blocks the operation.
    - Backward-compatible with old frontends that send model="__test__".
    """
    api_key = body.get("api_key", "").strip()
    model = body.get("model", "").strip()
    action = body.get("action", "setup")

    # 兼容旧前端：model 以 "__" 开头视为 test 模式
    if action == "setup" and model.startswith("__"):
        action = "test"

    if not api_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")

    # 拉取模型列表（best-effort）
    result = list_available_models(api_key=api_key)
    available_models = result.get("models", [])

    # 认证失败 → 阻断
    if not result["ok"] and result.get("error_kind") == "auth_error":
        raise HTTPException(
            status_code=400,
            detail=result.get("warning", "API Key 验证失败"),
        )

    # 仅测试连接（action=test 或 model 为空）
    if action == "test" or not model:
        return {
            "ok": result["ok"],
            "available_models": available_models,
            "warning": result.get("warning"),
            "models_source": "platform" if result["ok"] else "manual",
        }

    # Legacy write endpoints obey the same lock as the new active-config API.
    if has_session_overrides():
        raise HTTPException(409, "当前进程由启动参数锁定模型；请重启时移除覆盖参数")
    if _configuration_switch_blocked():
        raise HTTPException(409, "存在运行中或排队任务，暂不能切换决策模型")

    # 保存配置 — /models 成功时做推荐，失败时跳过校验
    if result["ok"] and model not in available_models:
        # 模型不在列表中，但仍允许保存
        save_api_key(api_key)
        save_remote_model(model, activate=True)
        return {
            "ok": True,
            "model": model,
            "available_models_count": len(available_models),
            "warning": f"模型 '{model}' 不在平台推荐列表中，已保存",
        }

    # 正常保存
    save_api_key(api_key)
    save_remote_model(model, activate=True)
    return {
        "ok": True,
        "model": model,
        "available_models_count": len(available_models),
    }


@app.put("/api/config/model")
async def update_model(body: dict):
    """更新决策模型（使用已保存的 API Key）。

    - model 为空字符串时：仅返回可用模型列表（不保存）
    - model 非空时：保存新模型（/models 仅做推荐，不阻断）
    """
    model = body.get("model", "").strip()

    # 检查是否已配置 API Key（不要求 backend 必须是 remote）
    if not get_api_key():
        raise HTTPException(status_code=400, detail="尚未完成初始配置，请先配置 API Key")

    # 用已保存的 Key 拉取模型列表
    result = list_available_models(api_key=get_api_key())
    available_models = result.get("models", [])

    # 空 model：仅返回模型列表（供 reconfigure 模式使用）
    if not model:
        return {
            "available_models": available_models,
            "ok": result["ok"],
            "warning": result.get("warning"),
        }

    if has_session_overrides():
        raise HTTPException(409, "当前进程由启动参数锁定模型；请重启时移除覆盖参数")
    if _configuration_switch_blocked():
        raise HTTPException(409, "存在运行中或排队任务，暂不能切换决策模型")

    # 保存 — /models 成功时做推荐，失败时跳过校验
    if result["ok"] and model not in available_models:
        save_remote_model(model, activate=False)
        return {
            "ok": True,
            "model": model,
            "available_models_count": len(available_models),
            "warning": f"模型 '{model}' 不在平台推荐列表中，已切换",
        }

    # 正常保存
    save_remote_model(model, activate=False)
    return {
        "ok": True,
        "model": model,
        "available_models_count": len(available_models),
    }


# ── 静态文件托管和主入口 ──────────────────────────────────
# 前端静态文件托管（展示模式）
frontend_dir = PROJECT_ROOT / "web" / "dist"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


def main():
    """启动 API 服务"""
    parser = argparse.ArgumentParser(description="TensileAgent local Web workbench")
    parser.add_argument("--agent-backend", choices=["local", "remote"], default=None)
    parser.add_argument("--agent-model", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.agent_model and not args.agent_backend:
        parser.error("--agent-model requires --agent-backend")
    set_session_overrides(backend=args.agent_backend, model=args.agent_model)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
