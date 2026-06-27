const API = "/api";

export interface Task {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  video_id: string;
  video_path: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: Record<string, unknown> | null;
  error: { stage: string; code: string; message: string } | null;
}

export interface AppConfig {
  active_backend: string;
  active_model: string | null;
  mock: boolean;
  runtime_dir: string;
  max_rounds: number;
}

export async function createTask(file?: File, videoPath?: string, videoId?: string): Promise<{ task_id: string }> {
  const form = new FormData();
  if (file) form.append("file", file);
  if (videoPath) form.append("video_path", videoPath);
  if (videoId) form.append("video_id", videoId);
  const res = await fetch(`${API}/tasks`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createBatchTasks(files: File[]): Promise<{ tasks: { task_id: string; video_id: string; status: string }[] }> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  const res = await fetch(`${API}/tasks/batch`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listTasks(limit = 50): Promise<Task[]> {
  const res = await fetch(`${API}/tasks?limit=${limit}`);
  return res.json();
}

export async function getTask(taskId: string): Promise<Task> {
  const res = await fetch(`${API}/tasks/${taskId}`);
  if (!res.ok) throw new Error("not found");
  return res.json();
}

export async function deleteTask(taskId: string): Promise<void> {
  await fetch(`${API}/tasks/${taskId}`, { method: "DELETE" });
}

export function subscribeEvents(taskId: string, onEvent: (event: unknown) => void): () => void {
  const es = new EventSource(`${API}/tasks/${taskId}/events`);
  es.onmessage = (e) => {
    try { onEvent(JSON.parse(e.data)); } catch { /* ignore */ }
  };
  es.onerror = () => { /* reconnect automatically */ };
  return () => es.close();
}

export async function getConfig(): Promise<AppConfig> {
  const res = await fetch(`${API}/config`);
  return res.json();
}

export async function getHealth(): Promise<{ ok: boolean; tasks: number; queue_size: number }> {
  const res = await fetch(`${API}/health`);
  return res.json();
}

export function getExportUrl(taskId: string, fmt: "json" | "jsonl" | "csv"): string {
  return `${API}/tasks/${taskId}/export?fmt=${fmt}`;
}

// ── Config Setup Types ──

export interface ConfigStatus {
  active_backend: string;
  configured: boolean;
  remote: {
    has_api_key: boolean;
    current_model: string | null;
    api_key_masked: string | null;
  };
  local: {
    current_model: string | null;
  };
}

export interface AvailableModel {
  id: string;
}

// ── Config Setup API ──

export async function getConfigStatus(): Promise<ConfigStatus> {
  const res = await fetch("/api/config/status");
  if (!res.ok) throw new Error("获取配置状态失败");
  return res.json();
}

export async function setupConfig(
  apiKey: string,
  model: string,
  action: "test" | "setup" = "setup"
): Promise<{
  ok: boolean;
  model?: string;
  available_models?: string[];
  available_models_count?: number;
  warning?: string;
  models_source?: string;
}> {
  const res = await fetch("/api/config/setup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey, model, action }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "配置失败");
  return data;
}

export async function updateModel(model: string): Promise<{ ok?: boolean; model?: string; available_models?: string[]; available_models_count?: number; warning?: string }> {
  const res = await fetch("/api/config/model", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || "更新模型失败");
  }
  return data;
}
