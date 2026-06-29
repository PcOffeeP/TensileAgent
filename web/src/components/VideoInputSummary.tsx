import { PlaySquare, Calendar, Clock, CheckCircle, AlertCircle, Activity } from "lucide-react";
import type { Task } from "../api";

interface VideoInputSummaryProps {
  task: Task;
}

export default function VideoInputSummary({ task }: VideoInputSummaryProps) {
  const isRunning = task.status === "running";
  const isCompleted = task.status === "completed";
  const isFailed = task.status === "failed";

  return (
    <div className="glass-panel p-4 rounded-xl border border-slate-200 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white/80">
      <div className="flex items-center gap-4">
        <div className="w-12 h-12 bg-[#002FA7]/10 rounded-lg flex items-center justify-center border border-[#002FA7]/20 shrink-0">
          <PlaySquare className="w-6 h-6 text-[#002FA7]" />
        </div>
        <div>
          <div className="flex items-center gap-2 mb-1">
            <h2 className="text-base font-bold text-slate-800">
              {task.video_name || task.video_id}
            </h2>
            <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider flex items-center gap-1 border
              ${isRunning ? 'bg-blue-50 text-blue-600 border-blue-200' : 
                isCompleted ? 'bg-emerald-50 text-emerald-600 border-emerald-200' :
                isFailed ? 'bg-rose-50 text-rose-600 border-rose-200' :
                'bg-slate-100 text-slate-600 border-slate-200'}`}
            >
              {isRunning && <Activity className="w-3 h-3 animate-spin" />}
              {isCompleted && <CheckCircle className="w-3 h-3" />}
              {isFailed && <AlertCircle className="w-3 h-3" />}
              {task.status}
            </span>
          </div>
          <div className="text-xs text-slate-500 font-mono">
            Task ID: {task.id}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-6 text-xs text-slate-500 bg-slate-50 px-4 py-2 rounded-lg border border-slate-100">
        <div className="flex items-center gap-2">
          <Calendar className="w-3.5 h-3.5 opacity-60" />
          <div className="flex flex-col">
            <span className="text-[10px] uppercase tracking-wider opacity-60 font-semibold">创建于</span>
            <span>{new Date(task.created_at).toLocaleString()}</span>
          </div>
        </div>
        {task.started_at && (
          <div className="flex items-center gap-2">
            <Clock className="w-3.5 h-3.5 opacity-60" />
            <div className="flex flex-col">
              <span className="text-[10px] uppercase tracking-wider opacity-60 font-semibold">开始于</span>
              <span>{new Date(task.started_at).toLocaleTimeString()}</span>
            </div>
          </div>
        )}
        {task.finished_at && (
          <div className="flex items-center gap-2">
            <CheckCircle className="w-3.5 h-3.5 opacity-60" />
            <div className="flex flex-col">
              <span className="text-[10px] uppercase tracking-wider opacity-60 font-semibold">完成于</span>
              <span>{new Date(task.finished_at).toLocaleTimeString()}</span>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
