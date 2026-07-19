const API = "/api";

export interface FinalResult {
  schema_version: "tensile-agent/result/v2";
  video_id: string;
  status: "fracture" | "no_fracture" | "unrecognized";
  has_fracture: boolean | null;
  time_range: [number, number] | null;
  fracture_type: string | null;
  location: "inside_gauge" | "outside_gauge" | null;
  field_status: Record<
    "has_fracture" | "time_range" | "fracture_type" | "location" | "confidence" | "visual_evidence",
    "available" | "unavailable" | "not_applicable"
  >;
  confidence: {
    decision: number | null;
    localization: number | null;
    classification: number | null;
    overall: number | null;
    evidence_level: "high" | "medium" | "low" | "insufficient";
    calibration_version: string | null;
  } | null;
  visual_evidence?: {
    status: "not_requested" | "available" | "unavailable";
    reliability: "experimental";
    summary: string | null;
    references: Array<{
      round: number;
      sample_range: [number, number];
      frame_timestamps: number[];
      clip_hash: string | null;
      request_id: string | null;
    }>;
  };
  unrecognized_reason: string | null;
  warnings: string[];
  rounds?: number;
  frame_range?: [number, number] | null;
}

export interface Task {
  id: string;
  status: "queued" | "running" | "completed" | "failed";
  video_id: string;
  video_name?: string;
  video_path?: string; // Keep as optional if still returned but don't show
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: FinalResult | null;
  response?: {
    status: "answered" | "partial" | "unrecognized" | "failed";
    answer: Record<string, unknown> | null;
    evidence_available: boolean;
    error: { code: string; message: string } | null;
  } | null;
  error: { stage: string; code: string; message: string } | null;
  decision_model?: ModelSnapshot | null;
}

export interface ModelSnapshot {
  backend: "local" | "remote" | string;
  provider: string | null;
  model: string | null;
  base_url: string | null;
  reasoning_effort: string;
  digest?: string | null;
}

export interface ModelOption {
  id: string;
  digest?: string | null;
  size?: number | null;
  modified_at?: string | null;
}

export interface LlmTrace {
  schema_version: number;
  task_id: string;
  round: number;
  request_id: string;
  model: ModelSnapshot;
  request: Record<string, unknown>;
  response: Record<string, unknown> | null;
  elapsed_seconds: number;
  error: { type: string; message: string } | null;
}

export interface AgentEvent {
  task_id?: string;
  event: string;
  timestamp?: string;
  data?: Record<string, any>;
}

export interface AnalysisRound {
  round: number;
  displayRound: number;
  stateAtStart?: string;
  candidateAtStart?: [number, number];
  toolCall?: {
    name: "sample_and_infer" | "terminate" | string;
    args: Record<string, any>;
    reasoning?: string;
    validationError?: string;
  };
  sampleRange?: [number, number];
  modelOutput?: {
    has_fracture?: boolean | null;
    fracture_between?: [number, number] | null;
    type?: string;
    location?: string | null;
  } | null;
  inferredTimeRange?: [number, number] | null;
  inferredFrameRange?: [number, number] | null;
  validationError?: { code?: string; message?: string; field?: string | null } | null;
  confidenceLevel?: "高" | "中" | "低" | "不可信" | string;
  previousState?: string;
  nextState?: string;
  previousCandidate?: [number, number];
  nextCandidate?: [number, number];
  terminationRequest?: {
    allowed: boolean;
    reason: string;
    args: Record<string, any>;
  };
}

export interface AnalysisTrace {
  taskId: string;
  videoDurationSec: number | null;
  initialCandidate: [number, number] | null;
  rounds: AnalysisRound[];
  finalResult: FinalResult | null;
  taskError: { stage?: string; code?: string; message: string } | null;
  connectionState: "connecting" | "open" | "reconnecting" | "closed" | "error";
  rawEvents: AgentEvent[];
}

export interface AppConfig {
  active_backend: string;
  active_model: string | null;
  mock: boolean;
  runtime_dir: string;
  max_rounds: number;
  active_digest?: string | null;
  ollama_ok?: boolean;
  reasoning_effort?: string;
  switch_allowed?: boolean;
  session_override?: boolean;
}

export async function createTask(file?: File, videoPath?: string, videoId?: string, question?: string): Promise<Task & { task_id: string }> {
  const form = new FormData();
  if (file) form.append("file", file);
  if (videoPath) form.append("video_path", videoPath);
  if (videoId) form.append("video_id", videoId);
  if (question) form.append("question", question);
  const res = await fetch(`${API}/tasks`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function createBatchTasks(files: File[], question?: string): Promise<{ tasks: (Task & { task_id: string })[] }> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  if (question) form.append("question", question);
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

export async function replayEvents(taskId: string): Promise<AgentEvent[]> {
  const res = await fetch(`${API}/tasks/${taskId}/events/replay`);
  if (!res.ok) throw new Error("Failed to replay events");
  const text = await res.text();
  if (!text.trim()) return [];
  try {
    return JSON.parse(text);
  } catch {
    return text.split('\n').filter(Boolean).map(line => JSON.parse(line));
  }
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
    service_ok?: boolean;
    installed?: boolean;
    digest?: string | null;
    warning?: string | null;
    reasoning_effort?: string;
  };
  switch_allowed?: boolean;
  session_override?: boolean;
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

export async function listDecisionModels(backend: "local" | "remote"): Promise<{ ok: boolean; models: ModelOption[]; warning?: string }> {
  const res = await fetch(`/api/config/models?backend=${backend}`);
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "获取模型列表失败");
  return data;
}

export async function testDecisionModel(backend: "local" | "remote", model: string): Promise<void> {
  const res = await fetch("/api/config/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ backend, model }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "模型连接测试失败");
}

export async function activateDecisionModel(backend: "local" | "remote", model: string, reasoningEffort = "none"): Promise<void> {
  const res = await fetch("/api/config/active", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ backend, model, reasoning_effort: reasoningEffort }),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "切换模型失败");
}

export async function getLlmTraces(taskId: string): Promise<LlmTrace[]> {
  const res = await fetch(`/api/tasks/${taskId}/llm-traces`);
  if (!res.ok) throw new Error("获取模型传输记录失败");
  return res.json();
}

export function getLlmTraceExportUrl(taskId: string): string {
  return `/api/tasks/${taskId}/llm-traces/export`;
}
