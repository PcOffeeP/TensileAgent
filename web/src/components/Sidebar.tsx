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
    <aside className="w-[260px] bg-white border-r border-slate-200 flex flex-col shrink-0 relative z-10">
      <div className="p-5 border-b border-slate-200">
        <h1 className="text-xl font-bold flex items-center gap-2 tracking-tight text-slate-900">
          <FlaskConical className="w-6 h-6 text-[#002FA7]" />
          TensileAgent
        </h1>
        <p className="tech-label mt-1.5">TENSILE · AGENT</p>
        {health && (
          <div
            className="flex items-center gap-1.5 mt-2.5"
            title={`服务${health.ok ? "正常" : "异常"} · 任务 ${health.tasks} · 队列 ${health.queue_size}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${health.ok ? "bg-emerald-500" : "bg-red-400"}`}></span>
            <span className="font-mono text-[10px] text-slate-400">任务 {health.tasks} · 队列 {health.queue_size}</span>
          </div>
        )}
      </div>
      <nav className="p-3 space-y-1.5 flex-1">
        <button onClick={() => onViewChange("analysis")} className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${currentView === "analysis" ? "bg-[#002FA7]/5 text-[#002FA7] shadow-[inset_2px_0_0_#002FA7]" : "text-slate-500 hover:text-slate-900 hover:bg-slate-100/80"}`}>
          <Play className="w-4 h-4" /> 实验分析
        </button>
        <button onClick={() => onViewChange("history")} className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${currentView === "history" ? "bg-[#002FA7]/5 text-[#002FA7] shadow-[inset_2px_0_0_#002FA7]" : "text-slate-500 hover:text-slate-900 hover:bg-slate-100/80"}`}>
          <History className="w-4 h-4" /> 历史记录
        </button>
        <button onClick={() => onViewChange("config")} className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-md text-sm font-medium transition-colors ${currentView === "config" ? "bg-[#002FA7]/5 text-[#002FA7] shadow-[inset_2px_0_0_#002FA7]" : "text-slate-500 hover:text-slate-900 hover:bg-slate-100/80"}`}>
          <Settings className="w-4 h-4" /> 系统配置
        </button>
      </nav>
      {config && (
        <div className="px-4 py-2.5 border-t border-slate-200 flex items-center gap-2">
          {config.mock && (
            <span className="shrink-0 text-[10px] text-amber-600 font-medium px-1.5 py-0.5 bg-amber-100/80 rounded border border-amber-500/20">Mock模式</span>
          )}
          <span
            className="text-[10px] leading-4 text-slate-400 font-mono truncate"
            title={`后端 ${config.active_backend} · 模型 ${config.active_model || "未配置"}`}
          >
            {config.active_backend} · {config.active_model || "未配置"}
          </span>
        </div>
      )}
    </aside>
  );
}
