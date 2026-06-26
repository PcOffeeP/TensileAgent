"""Agent 本地 Web 工作台 API"""
import asyncio
import csv
import io
import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agent.runner import run_one
from agent.config_util import (
    get_api_key,
    get_configured_model,
    is_remote_configured,
    list_available_models,
    save_api_key,
    save_model,
)

# ── 路径常量 ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / "data" / "08_runtime" / "web_workbench"
UPLOADS_DIR = RUNTIME_DIR / "uploads"
HISTORY_DIR = RUNTIME_DIR / "history"
EVENTS_DIR = RUNTIME_DIR / "events"
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
    video_path: str = ""
    config_path: str = ""
    created_at: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[dict] = None
    event_summary: Optional[dict] = None


# ── 全局状态 ──────────────────────────────────────────────
tasks: dict[str, TaskModel] = {}
task_queue: asyncio.Queue[str] = asyncio.Queue()
_queue_worker_task: Optional[asyncio.Task] = None
sse_connections: dict[str, list[asyncio.Queue]] = {}


# ── FastAPI 应用 ─────────────────────────────────────────
app = FastAPI(title="Agent Web Workbench API", version="1.0.0")


# ── 工具函数 ──────────────────────────────────────────────
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_path(task_id: str) -> Path:
    return HISTORY_DIR / f"{task_id}.json"


def _events_path(task_id: str) -> Path:
    return EVENTS_DIR / f"{task_id}.jsonl"


def _save_task(task: TaskModel):
    """持久化任务到 JSON"""
    d = task.model_dump()
    d["_schema_version"] = 1
    _task_path(task.id).write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def _restore_history():
    """服务启动时从磁盘恢复历史任务"""
    if not HISTORY_DIR.exists():
        return
    for f in sorted(HISTORY_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            t = TaskModel(**data)
            tasks[t.id] = t
        except Exception:
            continue


def _sanitize_event_data(data: dict) -> dict:
    """过滤敏感字段（Base64、token、API key、内部路径）"""
    safe = dict(data)
    for key in list(safe.keys()):
        if key in ("base64", "token", "api_key", "video_data"):
            safe.pop(key)
    return safe


def _append_event(task_id: str, event: dict):
    """追加事件到 JSONL 文件"""
    path = _events_path(task_id)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
    # 推送 SSE
    if task_id in sse_connections:
        dead = []
        for q in sse_connections[task_id]:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            sse_connections[task_id].remove(q)


def _event_callback_factory(task_id: str):
    """创建 runner 事件回调。runner 传入一个 dict，含 event 和其他字段。"""
    def callback(event_data: dict):
        event_type = event_data.get("event", "unknown")
        safe_data = _sanitize_event_data(event_data)
        event = {
            "task_id": task_id,
            "event": event_type,
            "data": safe_data,
            "timestamp": _now(),
        }
        _append_event(task_id, event)
    return callback


# ── SSE 事件流端点 ───────────────────────────────────────
@app.get("/api/tasks/{task_id}/events")
async def task_events(task_id: str):
    """SSE 事件流"""
    if task_id not in tasks:
        raise HTTPException(404, "task not found")

    queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    if task_id not in sse_connections:
        sse_connections[task_id] = []
    sse_connections[task_id].append(queue)

    async def event_generator():
        try:
            # 先发送已有的历史事件
            events_path = _events_path(task_id)
            if events_path.exists():
                for line in events_path.read_text(encoding="utf-8").strip().split("\n"):
                    if line:
                        try:
                            ev = json.loads(line)
                            yield {"data": json.dumps(ev)}
                        except Exception:
                            continue
            # 实时事件
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
            result = await loop.run_in_executor(
                None,
                lambda: run_one(
                    video_path=task.video_path,
                    config_path=config_path,
                    video_id=task.video_id,
                    event_callback=_event_callback_factory(task_id),
                )
            )

            # 规范化结果为公共结果
            task.result = _normalize_result(result)
            task.status = TASK_STATUS_COMPLETED

            _append_event(task_id, {
                "task_id": task_id,
                "event": "task_completed",
                "data": {"result": task.result},
                "timestamp": _now(),
            })
        except Exception as e:
            task.status = TASK_STATUS_FAILED
            task.error = {"stage": "runner", "code": type(e).__name__, "message": str(e)}
            _append_event(task_id, {
                "task_id": task_id,
                "event": "task_failed",
                "data": task.error,
                "timestamp": _now(),
            })
        finally:
            task.finished_at = _now()
            _save_task(task)


def _normalize_result(result: dict) -> dict:
    """将 runner 结果转为公共结果格式"""
    if not result:
        return {"status": "unrecognized"}

    output = result.get("output") or result.get("final_output") or {}
    return {
        "status": result.get("status", result.get("final_status", "unrecognized")),
        "video_id": result.get("video_id", ""),
        "type": output.get("type"),
        "location": output.get("location"),
        "confidence": output.get("confidence"),
        "fracture_between": output.get("fracture_between"),
        "start_time": result.get("start_time"),
        "end_time": result.get("end_time"),
        "rounds": result.get("rounds", result.get("total_rounds", 0)),
        "failure_stage": output.get("failure_stage") or result.get("failure_stage"),
        "error_code": output.get("error_code") or result.get("error_code"),
        "error_message": output.get("error_message") or result.get("message"),
    }


# ── 启动/关闭事件 ────────────────────────────────────────
@app.on_event("startup")
async def startup():
    """初始化目录、加载历史、启动队列 worker"""
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_DIR.mkdir(parents=True, exist_ok=True)
    _restore_history()
    global _queue_worker_task
    _queue_worker_task = asyncio.create_task(_queue_worker())


# ── API 端点 ─────────────────────────────────────────────
@app.get("/api/health")
async def health():
    """健康检查"""
    return {"ok": True, "status": "running", "tasks": len(tasks), "queue_size": task_queue.qsize()}


@app.get("/api/config")
async def get_config():
    """返回当前配置摘要（不包含密钥）"""
    cfg = {}
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            cfg = {"path": str(CONFIG_PATH)}
    return {
        "config_path": str(CONFIG_PATH),
        "mock": cfg.get("mock", False),
        "model": cfg.get("model", cfg.get("llm", {}).get("model", "unknown")),
        "runtime_dir": str(RUNTIME_DIR),
        "max_rounds": cfg.get("max_rounds", 10),
    }


@app.post("/api/tasks")
async def create_task(
    file: Optional[UploadFile] = File(None),
    video_path: Optional[str] = Form(None),
    video_id: Optional[str] = Form(None),
    config_path: Optional[str] = Form(None),
):
    """创建分析任务：支持上传文件、本地路径"""
    if not file and not video_path:
        raise HTTPException(400, "必须提供视频文件或视频路径")

    task_id = str(uuid.uuid4())
    vid = video_id or f"task_{task_id[:8]}"

    if file:
        # 保存上传文件
        upload_path = UPLOADS_DIR / f"{task_id}_{file.filename}"
        with upload_path.open("wb") as f:
            f.write(await file.read())
        vpath = str(upload_path)
    else:
        vpath = str(Path(video_path).resolve())
        if not os.path.isfile(vpath):
            raise HTTPException(400, f"视频文件不存在: {vpath}")

    task = TaskModel(
        id=task_id,
        video_id=vid,
        video_path=vpath,
        config_path=config_path or "",
        created_at=_now(),
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

    return {"task_id": task_id, "status": TASK_STATUS_QUEUED}


@app.get("/api/tasks")
async def list_tasks(limit: int = Query(50, ge=1, le=200)):
    """任务列表，按创建时间倒序"""
    sorted_tasks = sorted(tasks.values(), key=lambda t: t.created_at, reverse=True)
    return [t.model_dump() for t in sorted_tasks[:limit]]


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    if task_id not in tasks:
        raise HTTPException(404, "task not found")
    return tasks[task_id].model_dump()


@app.delete("/api/tasks/{task_id}")
async def delete_task(task_id: str):
    """删除任务及其数据"""
    if task_id not in tasks:
        raise HTTPException(404, "task not found")
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
    del tasks[task_id]
    return {"ok": True}


@app.get("/api/tasks/{task_id}/events/replay")
async def replay_events(task_id: str):
    """回放历史事件"""
    if task_id not in tasks:
        raise HTTPException(404, "task not found")
    path = _events_path(task_id)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").strip().split("\n")
    return [json.loads(l) for l in lines if l]


@app.get("/api/tasks/{task_id}/export")
async def export_result(task_id: str, fmt: str = Query("json", regex="^(json|jsonl|csv)$")):
    """导出分析结果"""
    if task_id not in tasks:
        raise HTTPException(404, "task not found")
    task = tasks[task_id]
    result = task.result or {}

    if fmt == "json":
        return JSONResponse(result)
    elif fmt == "jsonl":
        lines = [json.dumps(result, ensure_ascii=False)]
        return Response("\n".join(lines), media_type="application/x-ndjson")
    else:  # csv
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["video_id", "status", "type", "location", "confidence",
                         "start_time", "end_time", "rounds", "failure_stage", "error_code", "error_message"])
        writer.writerow([
            result.get("video_id", task.video_id),
            result.get("status", task.status),
            result.get("type", ""),
            result.get("location", ""),
            result.get("confidence", ""),
            result.get("start_time", ""),
            result.get("end_time", ""),
            result.get("rounds", 0),
            result.get("failure_stage", ""),
            result.get("error_code", ""),
            result.get("error_message", ""),
        ])
        return Response(output.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=result.csv"})


@app.post("/api/tasks/batch")
async def create_batch_tasks(
    files: list[UploadFile] = File(...),
    config_path: Optional[str] = Form(None),
):
    """批量上传并创建任务"""
    results = []
    for f in files:
        task_id = str(uuid.uuid4())
        upload_path = UPLOADS_DIR / f"{task_id}_{f.filename}"
        with upload_path.open("wb") as wf:
            wf.write(await f.read())
        vid = Path(f.filename).stem
        task = TaskModel(id=task_id, video_id=vid, video_path=str(upload_path),
                         config_path=config_path or "", created_at=_now())
        tasks[task_id] = task
        _save_task(task)
        await task_queue.put(task_id)
        results.append({"task_id": task_id, "video_id": vid, "status": TASK_STATUS_QUEUED})
    return {"tasks": results}


@app.get("/api/config/status")
async def get_config_status():
    """Check if remote backend is configured.

    Returns configuration status without exposing the full API key.
    """
    configured = is_remote_configured()
    api_key = get_api_key()
    masked_key = None
    if api_key and len(api_key) > 8:
        masked_key = api_key[:6] + "*" * (len(api_key) - 10) + api_key[-4:]

    return {
        "configured": configured,
        "has_api_key": bool(api_key),
        "has_model": bool(get_configured_model()),
        "api_key_masked": masked_key,
        "current_model": get_configured_model(),
    }


@app.post("/api/config/setup")
async def setup_config(body: dict):
    """Save API key and model, with connection test.

    Request body:
    {
        "api_key": "sk-...",
        "model": "qwen-max"
    }
    """
    api_key = body.get("api_key", "").strip()
    model = body.get("model", "").strip()

    if not api_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")
    if not model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")

    # Test connection by listing models
    models = list_available_models(api_key=api_key)
    if not models:
        raise HTTPException(
            status_code=400,
            detail="连接测试失败，请检查 API Key 是否正确",
        )

    # Verify the selected model is in the available list
    if model not in models:
        raise HTTPException(
            status_code=400,
            detail=f"模型 '{model}' 不在可用列表中。可用模型: {', '.join(models[:10])}",
        )

    # Save
    save_api_key(api_key)
    save_model(model)

    return {"ok": True, "model": model, "available_models_count": len(models)}


# ── 静态文件托管和主入口 ──────────────────────────────────
# 前端静态文件托管（展示模式）
frontend_dir = PROJECT_ROOT / "web" / "dist"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")


def main():
    """启动 API 服务"""
    uvicorn.run("agent.web_api:app", host="127.0.0.1", port=8765, reload=True)


if __name__ == "__main__":
    main()
