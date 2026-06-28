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
  running: <Activity className="w-3 h-3 text-[#002FA7] animate-spin" />,
  queued: <Clock className="w-3 h-3 text-amber-500" />,
  completed: <CheckCircle className="w-3 h-3 text-emerald-500" />,
  failed: <XCircle className="w-3 h-3 text-rose-500" />,
};

export default function Sidebar({ currentView, onViewChange, tasks, onSelectTask, config, health }: SidebarProps) {
  const recent = [...tasks].slice(0, 20);
  return (
    <aside className="w-[260px] bg-[rgba(255,255,255,0.85)] backdrop-blur-md border-r border-[var(--color-border)] flex flex-col shrink-0 relative z-10 shadow-[4px_0_24px_rgba(0,47,167,0.02)]">
      <div className="p-5 border-b border-[var(--color-border)]">
        <h1 className="text-xl font-bold flex items-center gap-2 tracking-tight text-slate-900">
          <FlaskConical className="w-6 h-6 text-[#002FA7]" />
          TensileAgent
        </h1>
        {health && (
          <div className="flex items-center gap-2 mt-3">
            <span className="flex h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.4)]"></span>
            <p className="text-xs text-slate-500 font-medium">
              任务: {health.tasks} · 队列: {health.queue_size}
            </p>
          </div>
        )}
      </div>
      <nav className="p-3 space-y-1.5">
        <button onClick={() => onViewChange("analysis")} className={`w-full flex items-center gap-3 px-3 py-2.5 rounded text-sm font-medium transition-colors ${currentView === "analysis" ? "bg-[#002FA7]/5 text-[#002FA7] shadow-sm border border-[#002FA7]/20" : "text-slate-500 hover:text-slate-900 hover:bg-slate-100/80 border border-transparent"}`}>
          <Play className="w-4 h-4" /> 实验分析
        </button>
        <button onClick={() => onViewChange("history")} className={`w-full flex items-center gap-3 px-3 py-2.5 rounded text-sm font-medium transition-colors ${currentView === "history" ? "bg-[#002FA7]/5 text-[#002FA7] shadow-sm border border-[#002FA7]/20" : "text-slate-500 hover:text-slate-900 hover:bg-slate-100/80 border border-transparent"}`}>
          <History className="w-4 h-4" /> 历史记录
        </button>
        <button onClick={() => onViewChange("config")} className={`w-full flex items-center gap-3 px-3 py-2.5 rounded text-sm font-medium transition-colors ${currentView === "config" ? "bg-[#002FA7]/5 text-[#002FA7] shadow-sm border border-[#002FA7]/20" : "text-slate-500 hover:text-slate-900 hover:bg-slate-100/80 border border-transparent"}`}>
          <Settings className="w-4 h-4" /> 系统配置
        </button>
      </nav>
      <div className="flex-1 overflow-auto p-3 custom-scrollbar">
        <p className="text-[11px] font-semibold text-slate-400 px-3 mb-2 uppercase tracking-wider">最近任务</p>
        {recent.map((t) => (
          <button key={t.id} onClick={() => onSelectTask(t.id)} className="w-full flex items-center gap-3 px-3 py-2 rounded text-xs text-left text-slate-600 hover:text-slate-900 hover:bg-slate-100/80 transition-colors">
            {statusIcon[t.status] || <Square className="w-3 h-3 text-slate-400" />}
            <span className="truncate flex-1 font-medium">{t.video_id}</span>
          </button>
        ))}
      </div>
      {config && (
        <div className="p-4 border-t border-[var(--color-border)] text-xs text-slate-500 bg-[#FAF9F6]/80 backdrop-blur">
          {config.mock && <span className="text-amber-600 font-medium mr-2 px-1.5 py-0.5 bg-amber-100/80 rounded border border-amber-500/20">Mock模式</span>}
          <span className="font-mono text-slate-700">{config.active_backend}</span>
          <span className="mx-2 text-slate-300">|</span>
          <span className="font-mono text-[#002FA7]">{config.active_model || "未配置"}</span>
        </div>
      )}
    </aside>
  );
}

