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
    <div>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[11px] text-slate-400">已脱敏的模型输入、工具调用与响应</p>
        <div className="flex gap-1.5">
          <button
            onClick={refresh}
            title="刷新"
            className="rounded-md border border-slate-200 bg-white p-1.5 text-slate-400 transition-colors hover:bg-slate-50 hover:text-slate-600"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
          <a
            href={getLlmTraceExportUrl(taskId)}
            download
            title="导出模型传输记录"
            className="rounded-md border border-slate-200 bg-white p-1.5 text-slate-400 transition-colors hover:bg-slate-50 hover:text-slate-600"
          >
            <Download className="h-3.5 w-3.5" />
          </a>
        </div>
      </div>
      <div className="space-y-2">
        {error && <p className="text-xs text-rose-600">{error}</p>}
        {!error && traces.length === 0 && (
          <p className="py-6 text-center text-xs text-slate-400">尚无决策模型调用记录。</p>
        )}
        {traces.map((trace) => (
          <details key={trace.request_id} className="rounded-md border border-slate-200 bg-slate-50">
            <summary className="cursor-pointer px-3 py-2 font-mono text-[11px] font-medium text-slate-600">
              Round {trace.round} · {trace.model.backend}/{trace.model.model} · {trace.elapsed_seconds}s
            </summary>
            <div className="space-y-3 border-t border-slate-200 p-3">
              <div>
                <p className="tech-label mb-1">REQUEST</p>
                <pre className="overflow-auto whitespace-pre-wrap break-all text-[10px] text-slate-700">
                  {JSON.stringify(trace.request, null, 2)}
                </pre>
              </div>
              <div>
                <p className="tech-label mb-1">RESPONSE</p>
                <pre className="overflow-auto whitespace-pre-wrap break-all text-[10px] text-slate-700">
                  {JSON.stringify(trace.response ?? trace.error, null, 2)}
                </pre>
              </div>
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}
