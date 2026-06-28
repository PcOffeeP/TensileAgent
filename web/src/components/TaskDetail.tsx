import { useState } from "react";
import { X, Download, Terminal, Activity, CheckCircle, AlertCircle, Clock, FileJson } from "lucide-react";
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
  running: "text-sky-400",
  queued: "text-amber-400",
};

const statusIcon: Record<string, React.ReactNode> = {
  running: <Activity className="w-4 h-4 text-sky-400 animate-spin" />,
  queued: <Clock className="w-4 h-4 text-amber-400" />,
  completed: <CheckCircle className="w-4 h-4 text-emerald-400" />,
  failed: <AlertCircle className="w-4 h-4 text-rose-400" />,
};

export default function TaskDetail({ task, events, onClose }: TaskDetailProps) {
  const [activeTab, setActiveTab] = useState<"logs" | "json">("logs");
  const result = task.result ?? {};
  const status: string = (result.status as string) || task.status;

  return (
    <div className="flex flex-col h-full bg-[rgba(255,255,255,0.95)] backdrop-blur-md relative z-10">
      {/* Sticky Header */}
      <div className="p-5 border-b border-[var(--color-border)] flex items-center justify-between sticky top-0 bg-white/90 backdrop-blur z-20 shadow-[0_4px_20px_rgba(0,47,167,0.02)]">
        <div className="flex items-center gap-3 overflow-hidden">
          {statusIcon[task.status] || <Activity className="w-4 h-4 text-slate-400" />}
          <h3 className="font-semibold text-sm text-slate-900 truncate">{task.video_id}</h3>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          <span className={`text-xs font-mono font-medium px-2 py-1 rounded bg-slate-50 border border-slate-200 ${statusColors[task.status] || "text-slate-500"}`}>
            {task.status.toUpperCase()}
          </span>
          <button onClick={onClose} className="p-1.5 hover:bg-slate-100 rounded-full transition-colors text-slate-400 hover:text-slate-600">
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto custom-scrollbar flex flex-col">
        {/* Top: Overview Header */}
        <div className="p-5 pb-0">
          <div className="bg-white rounded-xl p-4 shadow-sm border border-slate-200 mb-6">
            <div className="flex items-center justify-between mb-4">
              <span className="text-sm font-semibold text-slate-800 uppercase tracking-wider">Status Overview</span>
              <div className="flex gap-2">
                {["json", "csv"].map((f) => (
                  <a key={f} href={getExportUrl(task.id, f as any)} download className="flex items-center gap-1.5 px-2.5 py-1.5 bg-slate-50 hover:bg-slate-100 border border-slate-200 rounded text-xs font-medium text-slate-600 transition-colors shadow-sm">
                    <Download className="w-3.5 h-3.5" /> {f.toUpperCase()}
                  </a>
                ))}
              </div>
            </div>
            
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="bg-slate-50 p-3 rounded border border-slate-200">
                <span className="text-slate-500 text-[11px] uppercase tracking-wider mb-1 block">Final Status</span>
                <span className={`font-mono text-xs font-medium ${statusColors[status as string] || "text-slate-700"}`}>{status}</span>
              </div>
              {!!result.type && (
                <div className="bg-slate-50 p-3 rounded border border-slate-200">
                  <span className="text-slate-500 text-[11px] uppercase tracking-wider mb-1 block">Type</span>
                  <span className="font-medium text-xs text-slate-800">{String(result.type)}</span>
                </div>
              )}
              {!!result.location && (
                <div className="bg-slate-50 p-3 rounded border border-slate-200">
                  <span className="text-slate-500 text-[11px] uppercase tracking-wider mb-1 block">Location</span>
                  <span className="font-mono text-xs text-slate-800">{String(result.location)}</span>
                </div>
              )}
              {result.confidence != null && (
                <div className="bg-slate-50 p-3 rounded border border-slate-200">
                  <span className="text-slate-500 text-[11px] uppercase tracking-wider mb-1 block">Confidence</span>
                  <span className="font-mono text-xs text-slate-800">{Number(result.confidence).toFixed(2)}</span>
                </div>
              )}
            </div>
            
            {task.error && (
              <div className="mt-3 bg-rose-950/20 border border-rose-900/50 rounded p-3 text-xs text-rose-300">
                <p className="font-semibold flex items-center gap-2 mb-1"><AlertCircle className="w-4 h-4" /> {task.error.code}</p>
                <p className="opacity-90 font-mono">{task.error.message}</p>
              </div>
            )}
          </div>

          {/* Tabs Navigation */}
          <div className="flex items-center gap-6 border-b border-slate-200 mb-4 px-2">
            <button
              onClick={() => setActiveTab("logs")}
              className={`flex items-center gap-2 pb-3 text-sm font-medium transition-colors border-b-2 ${
                activeTab === "logs" ? "text-[#002FA7] border-[#002FA7]" : "text-slate-500 border-transparent hover:text-slate-700"
              }`}
            >
              <Terminal className="w-4 h-4" /> Execution Logs
            </button>
            <button
              onClick={() => setActiveTab("json")}
              className={`flex items-center gap-2 pb-3 text-sm font-medium transition-colors border-b-2 ${
                activeTab === "json" ? "text-[#002FA7] border-[#002FA7]" : "text-slate-500 border-transparent hover:text-slate-700"
              }`}
            >
              <FileJson className="w-4 h-4" /> Raw JSON
            </button>
          </div>
        </div>

        {/* Tab Content */}
        <div className="px-5 pb-5 flex-1 flex flex-col min-h-[300px]">
          {activeTab === "logs" && (
            <div className="bg-slate-50 border border-slate-200 shadow-inner rounded-lg p-4 flex-1 overflow-auto custom-scrollbar font-mono text-xs space-y-2">
              {events.length === 0 && (
                <div className="flex items-center gap-2 text-slate-500">
                  <Activity className="w-3 h-3 animate-spin" /> 等待事件流...
                </div>
              )}
              {events.map((ev: any, i) => (
                <div key={i} className="flex gap-3 text-slate-600 hover:bg-slate-100 px-2 py-1.5 rounded transition-colors -mx-2">
                  <span className="text-slate-400 shrink-0 select-none">{ev.timestamp?.slice(11, 19) || "--:--:--"}</span>
                  <div className="flex flex-wrap gap-x-2">
                    <span className={`font-medium ${
                      ev.event === "task_completed" ? "text-emerald-500" :
                      ev.event === "task_failed" ? "text-rose-500" :
                      ev.event === "task_started" ? "text-[#002FA7]" : "text-slate-600"
                    }`}>{ev.event}</span>
                    {ev.data?.video_id && <span className="text-slate-500 truncate max-w-[200px]">{ev.data.video_id}</span>}
                  </div>
                </div>
              ))}
            </div>
          )}

          {activeTab === "json" && (
            <div className="bg-slate-50 border border-slate-200 shadow-inner rounded-lg p-4 flex-1 overflow-auto custom-scrollbar font-mono text-xs text-slate-600">
              <pre>{JSON.stringify(task, null, 2)}</pre>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
