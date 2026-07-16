import { useEffect, useState } from "react";
import { Download, RefreshCw } from "lucide-react";
import { getLlmTraceExportUrl, getLlmTraces, type LlmTrace } from "../api";

export default function LlmTransportTrace({ taskId }: { taskId: string }) {
  const [traces, setTraces] = useState<LlmTrace[]>([]);
  const [error, setError] = useState("");

  async function refresh() {
    try {
      setTraces(await getLlmTraces(taskId));
      setError("");
    } catch (value: any) {
      setError(value.message || "加载失败");
    }
  }

  useEffect(() => { refresh(); }, [taskId]);

  return (
    <div className="glass-panel rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-800">模型传输</h3>
          <p className="text-[11px] text-slate-400">已脱敏的输入、工具与响应</p>
        </div>
        <div className="flex gap-2">
          <button onClick={refresh} className="rounded border border-slate-200 p-1.5 text-slate-500"><RefreshCw className="h-3.5 w-3.5" /></button>
          <a href={getLlmTraceExportUrl(taskId)} download className="rounded border border-slate-200 p-1.5 text-slate-500"><Download className="h-3.5 w-3.5" /></a>
        </div>
      </div>
      <div className="max-h-[360px] space-y-2 overflow-auto p-3">
        {error && <p className="text-xs text-rose-600">{error}</p>}
        {!error && traces.length === 0 && <p className="text-xs text-slate-400">尚无决策模型调用记录。</p>}
        {traces.map((trace) => (
          <details key={trace.request_id} className="rounded-lg border border-slate-200 bg-slate-50">
            <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-slate-700">
              Round {trace.round} · {trace.model.backend}/{trace.model.model} · {trace.elapsed_seconds}s
            </summary>
            <div className="space-y-3 border-t border-slate-200 p-3">
              <div><p className="mb-1 text-[11px] font-semibold text-slate-500">REQUEST</p><pre className="overflow-auto whitespace-pre-wrap break-all text-[10px] text-slate-700">{JSON.stringify(trace.request, null, 2)}</pre></div>
              <div><p className="mb-1 text-[11px] font-semibold text-slate-500">RESPONSE</p><pre className="overflow-auto whitespace-pre-wrap break-all text-[10px] text-slate-700">{JSON.stringify(trace.response ?? trace.error, null, 2)}</pre></div>
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}
