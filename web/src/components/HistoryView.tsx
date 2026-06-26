import { useState, useMemo } from "react";
import { Search, Trash2, ChevronRight, Play, CheckCircle, XCircle, Clock } from "lucide-react";
import type { Task } from "../api";

interface HistoryViewProps {
  tasks: Task[];
  onSelectTask: (id: string) => void;
  onDeleteTask: (id: string) => void;
}

const statusIcon: Record<string, React.ReactNode> = {
  running: <Play className="w-4 h-4 text-blue-400" />,
  queued: <Clock className="w-4 h-4 text-yellow-400" />,
  completed: <CheckCircle className="w-4 h-4 text-green-400" />,
  failed: <XCircle className="w-4 h-4 text-red-400" />,
};

export default function HistoryView({ tasks, onSelectTask, onDeleteTask }: HistoryViewProps) {
  const [search, setSearch] = useState("");
  const [filterStatus, setFilterStatus] = useState<string>("all");

  const filtered = useMemo(() => {
    return tasks.filter((t) => {
      if (filterStatus !== "all" && t.status !== filterStatus) return false;
      if (search && !t.video_id.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [tasks, search, filterStatus]);

  return (
    <div>
      <h2 className="text-xl font-bold mb-4">历史记录</h2>
      <div className="flex gap-2 mb-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-2.5 w-4 h-4 text-gray-500" />
          <input
            type="text"
            placeholder="搜索视频 ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 bg-gray-800 rounded text-sm outline-none focus:ring-1 focus:ring-cyan-400"
          />
        </div>
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="px-3 py-2 bg-gray-800 rounded text-sm outline-none focus:ring-1 focus:ring-cyan-400"
        >
          <option value="all">全部</option>
          <option value="completed">成功</option>
          <option value="failed">失败</option>
          <option value="running">运行中</option>
          <option value="queued">排队中</option>
        </select>
      </div>
      <div className="space-y-1">
        {filtered.map((t) => (
          <div key={t.id} className="flex items-center gap-3 px-4 py-2.5 bg-gray-900 rounded-lg hover:bg-gray-800 cursor-pointer group" onClick={() => onSelectTask(t.id)}>
            {statusIcon[t.status] || <Play className="w-4 h-4 text-gray-600" />}
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium truncate">{t.video_id}</p>
              <p className="text-xs text-gray-500">
                {t.created_at?.slice(0, 19).replace("T", " ") || ""}
                {t.result?.type ? ` · ${t.result.type}` : ""}
              </p>
            </div>
            <span className={`text-xs px-2 py-0.5 rounded ${
              t.status === "completed" ? "bg-green-900/50 text-green-300" :
              t.status === "failed" ? "bg-red-900/50 text-red-300" :
              t.status === "running" ? "bg-blue-900/50 text-blue-300" : "bg-yellow-900/50 text-yellow-300"
            }`}>
              {t.status}
            </span>
            <button
              onClick={(e) => { e.stopPropagation(); onDeleteTask(t.id); }}
              className="opacity-0 group-hover:opacity-100 p-1 hover:bg-gray-700 rounded"
            >
              <Trash2 className="w-4 h-4 text-red-400" />
            </button>
            <ChevronRight className="w-4 h-4 text-gray-600" />
          </div>
        ))}
        {filtered.length === 0 && <p className="text-center text-gray-600 py-8">暂无记录</p>}
      </div>
    </div>
  );
}
