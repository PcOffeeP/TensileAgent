import { FlaskConical, History, Settings, Play, Square, CheckCircle, XCircle, Clock } from "lucide-react";
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
  running: <Play className="w-3 h-3 text-blue-400" />,
  queued: <Clock className="w-3 h-3 text-yellow-400" />,
  completed: <CheckCircle className="w-3 h-3 text-green-400" />,
  failed: <XCircle className="w-3 h-3 text-red-400" />,
};

export default function Sidebar({ currentView, onViewChange, tasks, onSelectTask, config, health }: SidebarProps) {
  const recent = [...tasks].slice(0, 20);
  return (
    <aside className="w-[260px] bg-gray-900 border-r border-gray-800 flex flex-col">
      <div className="p-4 border-b border-gray-800">
        <h1 className="text-lg font-bold flex items-center gap-2">
          <FlaskConical className="w-5 h-5 text-cyan-400" />
          TensileAgent
        </h1>
        {health && (
          <p className="text-xs text-gray-500 mt-1">
            {health.tasks} tasks · queue: {health.queue_size}
          </p>
        )}
      </div>
      <nav className="p-2 space-y-1">
        <button onClick={() => onViewChange("analysis")} className={`w-full flex items-center gap-2 px-3 py-2 rounded text-sm ${currentView === "analysis" ? "bg-gray-800 text-cyan-400" : "text-gray-400 hover:text-gray-200"}`}>
          <Play className="w-4 h-4" /> 实验分析
        </button>
        <button onClick={() => onViewChange("history")} className={`w-full flex items-center gap-2 px-3 py-2 rounded text-sm ${currentView === "history" ? "bg-gray-800 text-cyan-400" : "text-gray-400 hover:text-gray-200"}`}>
          <History className="w-4 h-4" /> 历史记录
        </button>
        <button onClick={() => onViewChange("config")} className={`w-full flex items-center gap-2 px-3 py-2 rounded text-sm ${currentView === "config" ? "bg-gray-800 text-cyan-400" : "text-gray-400 hover:text-gray-200"}`}>
          <Settings className="w-4 h-4" /> 配置
        </button>
      </nav>
      <div className="flex-1 overflow-auto p-2">
        <p className="text-xs text-gray-600 px-3 mb-1">最近任务</p>
        {recent.map((t) => (
          <button key={t.id} onClick={() => onSelectTask(t.id)} className="w-full flex items-center gap-2 px-3 py-1.5 rounded text-xs text-left text-gray-400 hover:bg-gray-800">
            {statusIcon[t.status] || <Square className="w-3 h-3 text-gray-600" />}
            <span className="truncate flex-1">{t.video_id}</span>
          </button>
        ))}
      </div>
      {config && (
        <div className="p-3 border-t border-gray-800 text-xs text-gray-600">
          {config.mock && <span className="text-yellow-400 mr-2">Mock</span>}
          {config.model}
        </div>
      )}
    </aside>
  );
}
