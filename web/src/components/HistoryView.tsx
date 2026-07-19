import { useState, useMemo } from "react";
import { Search, Trash2, ChevronRight, Play, CheckCircle, XCircle, Clock } from "lucide-react";
import type { Task } from "../api";
import ActiveAnalysisWorkspace from "./ActiveAnalysisWorkspace";

interface HistoryViewProps {
  tasks: Task[];
  onSelectTask: (id: string) => void;
  onDeleteTask: (id: string) => void;
}

const statusIcon: Record<string, React.ReactNode> = {
  running: <Play className="w-4 h-4 text-[#002FA7]" />,
  queued: <Clock className="w-4 h-4 text-amber-500" />,
  completed: <CheckCircle className="w-4 h-4 text-emerald-500" />,
  failed: <XCircle className="w-4 h-4 text-rose-500" />,
};

const statusLabel: Record<string, string> = {
  running: "运行中",
  queued: "排队中",
  completed: "成功",
  failed: "失败",
};

function formatResultSummary(t: Task): string {
  if (!t.result) return "";
  switch (t.result.status) {
    case 'fracture':
      return ` · 发现断裂 (${t.result.time_range ? t.result.time_range.join('-') : '未知'})`;
    case 'no_fracture':
      return ' · 无断裂';
    case 'unrecognized':
      return ' · 无法识别';
    default:
      return "";
  }
}

function formatDateTime(isoString: string | undefined): string {
  if (!isoString) return "";
  try {
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return isoString.slice(0, 19).replace("T", " ");
    const pad = (n: number) => n.toString().padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  } catch {
    return isoString.slice(0, 19).replace("T", " ");
  }
}

export default function HistoryView({ tasks, onDeleteTask }: Omit<HistoryViewProps, 'onSelectTask'>) {
  const [search, setSearch] = useState("");
  const [filterStatus, setFilterStatus] = useState<string>("all");
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  const filtered = useMemo(() => {
    return tasks.filter((t) => {
      if (filterStatus !== "all" && t.status !== filterStatus) return false;
      if (search && !t.video_id.toLowerCase().includes(search.toLowerCase())) return false;
      return true;
    });
  }, [tasks, search, filterStatus]);

  if (selectedTaskId) {
    const task = tasks.find(t => t.id === selectedTaskId);
    if (!task) {
      setSelectedTaskId(null);
      return null;
    }
    return (
      <div className="h-full flex flex-col relative">
        <ActiveAnalysisWorkspace
          task={task}
          onClose={() => setSelectedTaskId(null)}
          onDelete={() => {
            onDeleteTask(selectedTaskId);
            setSelectedTaskId(null);
          }}
          isHistoryMode={true}
        />
      </div>
    );
  }

  return (
    <div>
      <h2 className="text-xl font-bold mb-4 text-slate-900">历史记录</h2>
      <div className="flex gap-2 mb-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-2.5 w-4 h-4 text-slate-400" />
          <input
            type="text"
            placeholder="搜索视频 ID..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full pl-9 pr-3 py-2 bg-white border border-slate-200 rounded-md text-sm text-slate-900 outline-none focus:border-[#002FA7]/50 focus:ring-2 focus:ring-[#002FA7]/20 transition-colors placeholder:text-slate-400"
          />
        </div>
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="px-3 py-2 bg-white border border-slate-200 rounded-md text-sm text-slate-900 outline-none focus:border-[#002FA7]/50 focus:ring-2 focus:ring-[#002FA7]/20 transition-colors"
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
          <div key={t.id} className="flex items-center gap-3 px-4 py-2.5 bg-white border border-slate-200 rounded-md hover:border-[#002FA7]/30 hover:bg-slate-50/60 cursor-pointer group transition-colors" onClick={() => setSelectedTaskId(t.id)}>
            {statusIcon[t.status] || <Play className="w-4 h-4 text-slate-400" />}
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-slate-900 truncate">{t.video_name || t.video_id}</p>
              <p className="text-xs text-slate-500">
                <span className="font-mono text-[11px]">{formatDateTime(t.created_at)}</span>
                {formatResultSummary(t)}
              </p>
            </div>
            <span className={`text-[11px] px-1.5 py-0.5 rounded ${
              t.status === "completed" ? "bg-emerald-50 text-emerald-600" :
              t.status === "failed" ? "bg-rose-50 text-rose-600" :
              t.status === "running" ? "bg-[#002FA7]/5 text-[#002FA7]" : "bg-amber-50 text-amber-600"
            }`}>
              {statusLabel[t.status] || t.status}
            </span>
            <button
              onClick={(e) => { e.stopPropagation(); onDeleteTask(t.id); }}
              className="opacity-0 group-hover:opacity-100 p-1 hover:bg-rose-50 rounded transition-colors"
            >
              <Trash2 className="w-4 h-4 text-rose-500" />
            </button>
            <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-slate-400 transition-colors" />
          </div>
        ))}
        {filtered.length === 0 && <p className="text-center text-slate-500 py-8">暂无记录</p>}
      </div>
    </div>
  );
}
