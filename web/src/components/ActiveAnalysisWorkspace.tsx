import { useAgentTaskEvents } from "../hooks/useAgentTaskEvents";
import { getExportUrl, type Task } from "../api";
import { ArrowLeft, RefreshCw, Download } from "lucide-react";
import VideoInputSummary from "./VideoInputSummary";
import FinalResultPanel from "./FinalResultPanel";
import IntervalConvergenceBar from "./IntervalConvergenceBar";
import AgentProgressTimeline from "./AgentProgressTimeline";
import RawEventLog from "./RawEventLog";
import LlmTransportTrace from "./LlmTransportTrace";

interface ActiveAnalysisWorkspaceProps {
  task: Task;
  onClose: () => void;
  onDelete?: () => void;
  isHistoryMode?: boolean;
}

export default function ActiveAnalysisWorkspace({ task, onClose, onDelete, isHistoryMode = false }: ActiveAnalysisWorkspaceProps) {
  const trace = useAgentTaskEvents(task.id);
  const isFinished = task.status === "completed" || task.status === "failed";

  return (
    <div className="h-full flex flex-col gap-4 max-w-7xl mx-auto w-full pb-6">
      {/* Header Actions */}
      <div className="flex items-center justify-between mb-2">
        <button 
          onClick={onClose}
          className="flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" /> 返回{isHistoryMode ? '列表' : ''}
        </button>
        <div className="flex items-center gap-3">
          <span className={`flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full border 
            ${trace.connectionState === 'open' ? 'bg-emerald-50 text-emerald-600 border-emerald-200' : 
              trace.connectionState === 'connecting' ? 'bg-amber-50 text-amber-600 border-amber-200' :
              trace.connectionState === 'error' ? 'bg-rose-50 text-rose-600 border-rose-200' :
              'bg-slate-50 text-slate-500 border-slate-200'}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${trace.connectionState === 'open' ? 'bg-emerald-500 animate-pulse' : 
              trace.connectionState === 'connecting' ? 'bg-amber-500' :
              trace.connectionState === 'error' ? 'bg-rose-500' : 'bg-slate-400'}`}></span>
            {trace.connectionState === 'open' ? '实时同步中' : 
             trace.connectionState === 'connecting' ? '连接中' : 
             trace.connectionState === 'error' ? '连接异常' : '连接已关闭'}
          </span>
          
          {isFinished ? (
            <div className="flex items-center gap-2">
              <a 
                href={getExportUrl(task.id, "json")} 
                download 
                className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-slate-200 text-slate-600 rounded text-xs hover:bg-slate-50 transition-colors shadow-sm"
              >
                <Download className="w-3.5 h-3.5" /> 导出 JSON
              </a>
              <a 
                href={getExportUrl(task.id, "csv")} 
                download 
                className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-slate-200 text-slate-600 rounded text-xs hover:bg-slate-50 transition-colors shadow-sm"
              >
                <Download className="w-3.5 h-3.5" /> 导出 CSV
              </a>
            </div>
          ) : (
            <button disabled className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-50 border border-slate-200 text-slate-400 rounded text-xs cursor-not-allowed">
              <Download className="w-3.5 h-3.5" /> 导出数据
            </button>
          )}

          {isHistoryMode && onDelete && (
            <button 
              onClick={onDelete}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-rose-50 border border-rose-200 text-rose-600 rounded text-xs hover:bg-rose-100 transition-colors shadow-sm ml-2"
            >
              删除记录
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
        <div className="flex-1 flex flex-col md:flex-row gap-4 min-h-0">
          <div className="flex-1 glass-panel rounded-xl border border-slate-200 overflow-hidden shadow-sm flex flex-col">
            <AgentProgressTimeline rounds={trace.rounds} />
          </div>
          <div className="w-full md:w-[380px] flex flex-col gap-4">
            <RawEventLog events={trace.rawEvents} />
            <LlmTransportTrace taskId={task.id} />
          </div>
        </div>
      </div>
    </div>
  );
}
