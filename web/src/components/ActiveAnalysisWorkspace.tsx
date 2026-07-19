import { useAgentTaskEvents } from "../hooks/useAgentTaskEvents";
import { getExportUrl, type AnalysisTrace, type Task } from "../api";
import { ArrowLeft, Download, Trash2 } from "lucide-react";
import VideoInputSummary from "./VideoInputSummary";
import FinalResultPanel from "./FinalResultPanel";
import IntervalConvergenceBar from "./IntervalConvergenceBar";
import AgentProgressTimeline from "./AgentProgressTimeline";
import DiagnosticsPanel from "./DiagnosticsPanel";

interface ActiveAnalysisWorkspaceProps {
  task: Task;
  onClose: () => void;
  onDelete?: () => void;
  isHistoryMode?: boolean;
}

const CONNECTION_META: Record<AnalysisTrace["connectionState"], { dot: string; text: string; label: string }> = {
  open: { dot: "bg-slate-300", text: "text-slate-400", label: "实时同步" },
  connecting: { dot: "bg-amber-500", text: "text-amber-600", label: "连接中…" },
  reconnecting: { dot: "bg-amber-500", text: "text-amber-600", label: "重连中…" },
  error: { dot: "bg-rose-500", text: "text-rose-600", label: "连接异常" },
  closed: { dot: "bg-slate-300", text: "text-slate-400", label: "连接已关闭" },
};

export default function ActiveAnalysisWorkspace({ task, onClose, onDelete, isHistoryMode = false }: ActiveAnalysisWorkspaceProps) {
  const trace = useAgentTaskEvents(task.id);
  const isFinished = task.status === "completed" || task.status === "failed";
  const connection = CONNECTION_META[trace.connectionState];

  return (
    <div className="h-full flex flex-col gap-4 max-w-7xl mx-auto w-full pb-6">
      {/* Header Actions */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-4">
          <button
            onClick={onClose}
            className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" /> 返回{isHistoryMode ? "列表" : ""}
          </button>
          <span className={`flex items-center gap-1.5 font-mono text-[11px] ${connection.text}`} title={`SSE 连接状态：${connection.label}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${connection.dot}`}></span>
            {connection.label}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {isFinished && (
            <>
              <a
                href={getExportUrl(task.id, "json")}
                download
                className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 transition-colors hover:border-slate-300 hover:bg-slate-50"
              >
                <Download className="w-3.5 h-3.5" /> 导出 JSON
              </a>
              <a
                href={getExportUrl(task.id, "csv")}
                download
                className="flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-3 py-1.5 text-xs text-slate-600 transition-colors hover:border-slate-300 hover:bg-slate-50"
              >
                <Download className="w-3.5 h-3.5" /> 导出 CSV
              </a>
            </>
          )}

          {isHistoryMode && onDelete && (
            <button
              onClick={onDelete}
              className="flex items-center gap-1.5 rounded-md border border-rose-200 bg-white px-3 py-1.5 text-xs text-rose-600 transition-colors hover:bg-rose-50"
            >
              <Trash2 className="w-3.5 h-3.5" /> 删除
            </button>
          )}
        </div>
      </div>

      <div className="flex flex-col gap-4 flex-1 overflow-hidden">
        {/* Top Summary & Result */}
        <VideoInputSummary task={task} />
        <FinalResultPanel
          result={trace.finalResult ?? task.result}
          error={trace.taskError ?? task.error}
          response={task.response}
        />
        <IntervalConvergenceBar trace={trace} fallbackResult={task.result} />

        {/* Main Work Area */}
        <div className="tech-panel tech-corners flex-1 min-h-0 overflow-hidden flex flex-col">
          <AgentProgressTimeline rounds={trace.rounds} />
        </div>

        <DiagnosticsPanel taskId={task.id} events={trace.rawEvents} />
      </div>
    </div>
  );
}
