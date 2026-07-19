import { PlaySquare, CheckCircle, AlertCircle, Activity } from "lucide-react";
import type { Task } from "../api";

interface VideoInputSummaryProps {
  task: Task;
}

export default function VideoInputSummary({ task }: VideoInputSummaryProps) {
  const isRunning = task.status === "running";
  const isCompleted = task.status === "completed";
  const isFailed = task.status === "failed";

  const detailTitle = [
    `Task ID: ${task.id}`,
    task.started_at ? `开始于 ${new Date(task.started_at).toLocaleString()}` : null,
    task.finished_at ? `完成于 ${new Date(task.finished_at).toLocaleString()}` : null,
  ]
    .filter(Boolean)
    .join("\n");

  return (
    <div
      className="tech-panel px-3 py-2 flex items-center gap-3"
      title={detailTitle}
    >
      <div className="w-8 h-8 bg-[#002FA7]/5 border border-[#002FA7]/15 rounded-md flex items-center justify-center shrink-0">
        <PlaySquare className="w-4 h-4 text-[#002FA7]" />
      </div>
      <h2 className="text-sm font-semibold text-slate-800 truncate">
        {task.video_name || task.video_id}
      </h2>
      <span
        className={`px-2 py-0.5 rounded font-mono text-[10px] uppercase tracking-wider flex items-center gap-1 border shrink-0
          ${isRunning ? 'bg-blue-50/70 text-blue-600 border-blue-200' :
            isCompleted ? 'bg-emerald-50/70 text-emerald-600 border-emerald-200' :
            isFailed ? 'bg-rose-50/70 text-rose-600 border-rose-200' :
            'bg-slate-50 text-slate-500 border-slate-200'}`}
      >
        {isRunning && <Activity className="w-3 h-3" />}
        {isCompleted && <CheckCircle className="w-3 h-3" />}
        {isFailed && <AlertCircle className="w-3 h-3" />}
        {task.status}
      </span>
      <span className="ml-auto font-mono text-[10px] text-slate-400 shrink-0">
        创建于 {new Date(task.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}
      </span>
    </div>
  );
}
