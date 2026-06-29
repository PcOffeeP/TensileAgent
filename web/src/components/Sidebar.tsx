import { FlaskConical, History, Settings, Play } from "lucide-react";
import type { AppConfig } from "../api";

interface SidebarProps {
  currentView: string;
  onViewChange: (v: "analysis" | "history" | "config") => void;
  config: AppConfig | null;
  health: { ok: boolean; tasks: number; queue_size: number } | null;
}

export default function Sidebar({ currentView, onViewChange, config, health }: SidebarProps) {
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
      <nav className="p-3 space-y-1.5 flex-1">
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

