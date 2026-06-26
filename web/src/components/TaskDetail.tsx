import { X, Download, Terminal } from "lucide-react";
import type { Task } from "../api";
import { getExportUrl } from "../api";

interface TaskDetailProps {
  task: Task;
  events: Record<string, unknown>[];
  onClose: () => void;
}

const statusColors: Record<string, string> = {
  completed: "text-green-400",
  failed: "text-red-400",
  running: "text-blue-400",
  queued: "text-yellow-400",
};

export default function TaskDetail({ task, events, onClose }: TaskDetailProps) {
  const result = task.result || {};
  const status = result.status || task.status;

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-bold text-sm truncate">{task.video_id}</h3>
        <div className="flex items-center gap-2">
          <span className={`text-xs ${statusColors[task.status] || ""}`}>{task.status}</span>
          <button onClick={onClose}><X className="w-4 h-4 text-gray-500 hover:text-gray-300" /></button>
        </div>
      </div>

      {/* 结果卡片 */}
      {task.result && (
        <div className="bg-gray-800 rounded-lg p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-400">分析结果</span>
            <div className="flex gap-1">
              {["json", "jsonl", "csv"].map((f) => (
                <a key={f} href={getExportUrl(task.id, f as any)} download className="flex items-center gap-1 px-2 py-1 bg-gray-700 rounded text-xs hover:bg-gray-600">
                  <Download className="w-3 h-3" /> {f}
                </a>
              ))}
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <div><span className="text-gray-500">状态</span><br /><span className={statusColors[status as string] || ""}>{status}</span></div>
            {result.type && <div><span className="text-gray-500">类型</span><br />{String(result.type)}</div>}
            {result.location && <div><span className="text-gray-500">位置</span><br />{String(result.location)}</div>}
            {result.confidence != null && <div><span className="text-gray-500">置信度</span><br />{Number(result.confidence).toFixed(2)}</div>}
            {result.rounds != null && <div><span className="text-gray-500">轮数</span><br />{String(result.rounds)}</div>}
          </div>
          {task.error && (
            <div className="bg-red-900/30 rounded p-2 text-xs text-red-300">
              <p className="font-medium">{task.error.code}</p>
              <p>{task.error.message}</p>
            </div>
          )}
        </div>
      )}

      {/* 折叠 JSON */}
      <details>
        <summary className="text-xs text-gray-400 cursor-pointer hover:text-gray-200">原始结果 (JSON)</summary>
        <pre className="mt-2 text-xs text-gray-500 bg-gray-900 rounded p-2 max-h-60 overflow-auto">
          {JSON.stringify(task, null, 2)}
        </pre>
      </details>

      {/* 事件日志 */}
      <div>
        <div className="flex items-center gap-2 text-xs text-gray-400 mb-2">
          <Terminal className="w-3 h-3" /> 事件日志 ({events.length})
        </div>
        <div className="bg-gray-900 rounded p-2 max-h-96 overflow-auto font-mono text-xs space-y-0.5">
          {events.length === 0 && <p className="text-gray-600">等待事件...</p>}
          {events.map((ev: any, i) => (
            <div key={i} className="text-gray-500">
              <span className="text-gray-600">{ev.timestamp?.slice(11, 19) || ""}</span>{" "}
              <span className={
                ev.event === "task_completed" ? "text-green-400" :
                ev.event === "task_failed" ? "text-red-400" :
                ev.event === "task_started" ? "text-blue-400" : "text-gray-400"
              }>{ev.event}</span>
              {ev.data?.video_id && <span className="text-gray-600"> {ev.data.video_id}</span>}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
