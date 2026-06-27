import { FlaskConical, History, Settings, Play, Square, CheckCircle, XCircle, Clock, Activity } from "lucide-react";
import type { Task, AppConfig } from "../api";

interface SidebarProps {
  currentView: string;
  onViewChange: (v: "analysis" | "history" | "config") => void;
  tasks: Task[];
  onSelectTask: (id: string) => void;
  config: AppConfig | null;
  health: { ok: boolean; tasks: number; queue_size: number } | null;
}

const statusIcon: Record<string, React.ReactNode> = {
  running: <Activity className="w-3 h-3 text-cyan-400 animate-spin" />,
  queued: <Clock className="w-3 h-3 text-amber-400" />,
  completed: <CheckCircle className="w-3 h-3 text-emerald-400" />,
  failed: <XCircle className="w-3 h-3 text-rose-400" />,
};

export default function Sidebar({ currentView, onViewChange, tasks, onSelectTask, config, health }: SidebarProps) {
  const recent = [...tasks].slice(0, 20);
  return (
    <aside className="w-[260px] bg-[#07070B] border-r border-slate-800/50 flex flex-col shrink-0 relative z-10">
      <div className="p-5 border-b border-slate-800/50">
        <h1 className="text-xl font-bold flex items-center gap-2 tracking-tight text-slate-100">
          <FlaskConical className="w-6 h-6 text-cyan-500" />
          TensileAgent
        </h1>
        {health && (
          <div className="flex items-center gap-2 mt-3">
            <span className="flex h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)]"></span>
            <p className="text-xs text-slate-400 font-medium">
              任务: {health.tasks} · 队列: {health.queue_size}
            </p>
          </div>
        )}
      </div>
      <nav className="p-3 space-y-1.5">
        <button onClick={() => onViewChange("analysis")} className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${currentView === "analysis" ? "bg-cyan-900/30 text-cyan-400" : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"}`}>
          <Play className="w-4 h-4" /> 实验分析
        </button>
        <button onClick={() => onViewChange("history")} className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${currentView === "history" ? "bg-cyan-900/30 text-cyan-400" : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"}`}>
          <History className="w-4 h-4" /> 历史记录
        </button>
        <button onClick={() => onViewChange("config")} className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${currentView === "config" ? "bg-cyan-900/30 text-cyan-400" : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"}`}>
          <Settings className="w-4 h-4" /> 系统配置
        </button>
      </nav>
      <div className="flex-1 overflow-auto p-3">
        <p className="text-xs font-semibold text-slate-500 px-3 mb-2 tracking-wider">最近任务</p>
        {recent.map((t) => (
          <button key={t.id} onClick={() => onSelectTask(t.id)} className="w-full flex items-center gap-3 px-3 py-2 rounded-lg text-xs text-left text-slate-400 hover:text-slate-200 hover:bg-slate-800/50 transition-colors">
            {statusIcon[t.status] || <Square className="w-3 h-3 text-slate-600" />}
            <span className="truncate flex-1 font-medium">{t.video_id}</span>
          </button>
        ))}
      </div>
      {config && (
        <div className="p-4 border-t border-slate-800/50 text-xs text-slate-500 bg-slate-900/20 backdrop-blur">
          {config.mock && <span className="text-amber-400 font-medium mr-2 px-1.5 py-0.5 bg-amber-900/30 rounded">Mock模式</span>}
          <span className="font-mono">{config.active_backend}</span>
          <span className="mx-2">·</span>
          <span className="font-mono text-cyan-500/80">{config.active_model || "未配置"}</span>
        </div>
      )}
    </aside>
  );
}
