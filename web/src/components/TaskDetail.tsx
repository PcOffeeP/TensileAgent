import { X, Download, Terminal, Activity, CheckCircle, AlertCircle, Clock } from "lucide-react";
import type { Task } from "../api";
import { getExportUrl } from "../api";

interface TaskDetailProps {
  task: Task;
  events: Record<string, unknown>[];
  onClose: () => void;
}

const statusColors: Record<string, string> = {
  completed: "text-emerald-400",
  failed: "text-rose-400",
  running: "text-cyan-400",
  queued: "text-amber-400",
};

const statusIcon: Record<string, React.ReactNode> = {
  running: <Activity className="w-4 h-4 text-cyan-400 animate-spin" />,
  queued: <Clock className="w-4 h-4 text-amber-400" />,
  completed: <CheckCircle className="w-4 h-4 text-emerald-400" />,
  failed: <AlertCircle className="w-4 h-4 text-rose-400" />,
};

export default function TaskDetail({ task, events, onClose }: TaskDetailProps) {
  const result = task.result ?? {};
  const status: string = (result.status as string) || task.status;

  return (
    <div className="flex flex-col h-full bg-[#0A0A0F] border-l border-slate-800/50 relative z-10">
      <div className="p-5 border-b border-slate-800/50 flex items-center justify-between sticky top-0 bg-[#0A0A0F]/80 backdrop-blur z-20">
        <div className="flex items-center gap-3 overflow-hidden">
          {statusIcon[task.status] || <Activity className="w-4 h-4 text-slate-500" />}
          <h3 className="font-semibold text-sm text-slate-100 truncate">{task.video_id}</h3>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className={`text-xs font-medium px-2 py-1 rounded bg-slate-800/50 ${statusColors[task.status] || "text-slate-400"}`}>
            {task.status.toUpperCase()}
          </span>
          <button onClick={onClose} className="p-1 hover:bg-slate-800 rounded-full transition-colors text-slate-400 hover:text-slate-200">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="p-5 space-y-6 overflow-y-auto custom-scrollbar flex-1">
        {/* 结果卡片 */}
        {task.result && (
          <div className="glass-panel rounded-xl p-4 shadow-lg">
            <div className="flex items-center justify-between mb-4">
              <span className="text-sm font-semibold text-slate-200 tracking-wide">分析结果</span>
              <div className="flex gap-2">
                {["json", "jsonl", "csv"].map((f) => (
                  <a key={f} href={getExportUrl(task.id, f as any)} download className="flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-800 hover:bg-slate-700 border border-slate-700/50 rounded-md text-xs font-medium text-slate-300 transition-colors shadow-sm">
                    <Download className="w-3.5 h-3.5" /> {f.toUpperCase()}
                  </a>
                ))}
              </div>
            </div>
            
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="bg-slate-900/50 p-3 rounded-lg border border-slate-800/50">
                <span className="text-slate-500 text-xs mb-1 block">状态</span>
                <span className={`font-medium ${statusColors[status as string] || "text-slate-300"}`}>{status}</span>
              </div>
              {!!result.type && (
                <div className="bg-slate-900/50 p-3 rounded-lg border border-slate-800/50">
                  <span className="text-slate-500 text-xs mb-1 block">类型</span>
                  <span className="font-medium text-slate-200">{String(result.type)}</span>
                </div>
              )}
              {!!result.location && (
                <div className="bg-slate-900/50 p-3 rounded-lg border border-slate-800/50">
                  <span className="text-slate-500 text-xs mb-1 block">断裂位置</span>
                  <span className="font-mono text-slate-200">{String(result.location)}</span>
                </div>
              )}
              {result.confidence != null && (
                <div className="bg-slate-900/50 p-3 rounded-lg border border-slate-800/50">
                  <span className="text-slate-500 text-xs mb-1 block">置信度</span>
                  <span className="font-medium text-slate-200">{Number(result.confidence).toFixed(2)}</span>
                </div>
              )}
              {result.rounds != null && (
                <div className="bg-slate-900/50 p-3 rounded-lg border border-slate-800/50">
                  <span className="text-slate-500 text-xs mb-1 block">推理轮数</span>
                  <span className="font-medium text-slate-200">{String(result.rounds)}</span>
                </div>
              )}
            </div>
            
            {task.error && (
              <div className="mt-3 bg-rose-950/20 border border-rose-900/50 rounded-lg p-3 text-sm text-rose-300">
                <p className="font-semibold flex items-center gap-2"><AlertCircle className="w-4 h-4" /> {task.error.code}</p>
                <p className="mt-1 opacity-90">{task.error.message}</p>
              </div>
            )}
          </div>
        )}

        {/* 折叠 JSON */}
        <details className="group">
          <summary className="flex items-center gap-2 text-sm font-medium text-slate-400 cursor-pointer hover:text-slate-200 transition-colors list-none">
            <span className="w-4 h-4 border border-slate-600 rounded flex items-center justify-center text-[10px] group-open:bg-slate-800">{`{}`}</span>
            原始数据 (JSON)
          </summary>
          <pre className="mt-3 text-xs text-slate-400 bg-[#050508] border border-slate-800/50 rounded-lg p-4 max-h-60 overflow-auto custom-scrollbar shadow-inner font-mono">
            {JSON.stringify(task, null, 2)}
          </pre>
        </details>

        {/* 事件日志 */}
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-300 mb-3 tracking-wide">
            <Terminal className="w-4 h-4 text-slate-500" /> 实时事件日志
            <span className="bg-slate-800 text-slate-400 text-[10px] px-1.5 py-0.5 rounded-full">{events.length}</span>
          </div>
          <div className="bg-[#050508] border border-slate-800/50 shadow-inner rounded-lg p-4 max-h-[400px] overflow-auto custom-scrollbar font-mono text-xs space-y-2">
            {events.length === 0 && (
              <div className="flex items-center gap-2 text-slate-600">
                <Activity className="w-3 h-3 animate-spin" /> 等待事件流...
              </div>
            )}
            {events.map((ev: any, i) => (
              <div key={i} className="flex gap-3 text-slate-500 hover:bg-slate-900/50 px-2 py-1 rounded transition-colors -mx-2">
                <span className="text-slate-600 shrink-0">{ev.timestamp?.slice(11, 19) || "--:--:--"}</span>
                <div className="flex flex-wrap gap-x-2">
                  <span className={`font-medium ${
                    ev.event === "task_completed" ? "text-emerald-400" :
                    ev.event === "task_failed" ? "text-rose-400" :
                    ev.event === "task_started" ? "text-cyan-400" : "text-slate-400"
                  }`}>{ev.event}</span>
                  {ev.data?.video_id && <span className="text-slate-600 truncate max-w-[200px]">{ev.data.video_id}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
