import { CheckCircle, AlertCircle, HelpCircle, XCircle } from "lucide-react";
import type { FinalResult } from "../api";

interface FinalResultPanelProps {
  result: FinalResult | null;
  error: { stage?: string; code?: string; message: string } | null;
  response?: {
    status: "answered" | "unrecognized" | "failed";
    answer: Record<string, unknown> | null;
    evidence_available: boolean;
    error: { code: string; message: string } | null;
  } | null;
}

const FIELD_LABELS: Record<string, string> = {
  has_fracture: "是否断裂",
  time_range: "断裂时间",
  type: "断裂类型",
  location: "断裂位置",
  confidence: "置信度",
  visual_evidence: "视觉依据",
};

function formatAnswerValue(key: string, value: unknown): string {
  if (key === "has_fracture") return value === true ? "是" : value === false ? "否" : "无法判断";
  if (key === "time_range" && Array.isArray(value)) return `${value[0]}s - ${value[1]}s`;
  if (key === "visual_evidence" && value && typeof value === "object") {
    return String((value as { summary?: string | null }).summary ?? "视觉依据暂不可用");
  }
  if (key === "confidence" && value && typeof value === "object") {
    const confidence = value as { overall?: number | null; evidence_level?: string };
    return confidence.overall != null
      ? `${(confidence.overall * 100).toFixed(0)}%`
      : `尚未校准（证据等级：${confidence.evidence_level ?? "insufficient"}）`;
  }
  return value == null ? "不适用或无法确定" : String(value);
}

export default function FinalResultPanel({ result, error, response }: FinalResultPanelProps) {
  const overallConfidence = result?.confidence?.overall ?? null;
  if (error) {
    return (
      <div className="bg-rose-50 border-2 border-rose-200 rounded-xl p-5 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="w-10 h-10 rounded-full bg-rose-100 flex items-center justify-center shrink-0">
            <XCircle className="w-6 h-6 text-rose-600" />
          </div>
          <div>
            <h3 className="text-lg font-bold text-rose-800 mb-1">分析任务失败</h3>
            <div className="text-sm text-rose-700 bg-white/50 p-3 rounded border border-rose-100 mt-2">
              {error.stage && <div><strong>Stage:</strong> {error.stage}</div>}
              {error.code && <div><strong>Code:</strong> {error.code}</div>}
              {(error as any).error && !error.code && <div><strong>Error:</strong> {(error as any).error}</div>}
              <div className="mt-1"><strong>Message:</strong> {error.message ?? "Unknown error"}</div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (!result) return null;

  if (response?.status === "answered" && response.answer) {
    return (
      <div className="bg-white border-2 border-blue-100 rounded-xl p-5 shadow-sm">
        <h3 className="text-xl font-bold text-slate-900 mb-4">分析回答</h3>
        <div className="space-y-3">
          {Object.entries(response.answer).map(([key, value]) => (
            <div key={key} className="flex gap-4 border-b border-slate-100 pb-3 last:border-0 last:pb-0">
              <span className="w-24 shrink-0 text-sm font-semibold text-slate-500">{FIELD_LABELS[key] ?? key}</span>
              <span className="text-sm text-slate-900">{formatAnswerValue(key, value)}</span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (result.status === "fracture") {
    return (
      <div className="bg-emerald-50 border-2 border-emerald-200 rounded-xl p-5 shadow-sm relative overflow-hidden">
        <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-100/50 rounded-full blur-3xl -translate-y-1/2 translate-x-1/2"></div>
        <div className="flex items-start gap-4 relative z-10">
          <div className="w-12 h-12 rounded-full bg-emerald-500 flex items-center justify-center shrink-0 shadow-md">
            <CheckCircle className="w-7 h-7 text-white" />
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-3 mb-2">
              <h3 className="text-xl font-bold text-emerald-800">发现断裂 (Fracture)</h3>
              {overallConfidence != null && (
                <span className="px-2 py-0.5 bg-emerald-100 text-emerald-700 text-xs font-bold rounded-full border border-emerald-200">
                  置信度: {(overallConfidence * 100).toFixed(0)}%
                </span>
              )}
            </div>
            
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
              <div className="bg-white/80 p-3 rounded-lg border border-emerald-100/50">
                <div className="text-[10px] text-emerald-600/70 font-semibold uppercase tracking-wider mb-1">断裂时间区间</div>
                <div className="text-emerald-900 font-mono font-medium">
                  {result.time_range ? `${result.time_range[0]}s - ${result.time_range[1]}s` : '未知'}
                </div>
              </div>
              <div className="bg-white/80 p-3 rounded-lg border border-emerald-100/50">
                <div className="text-[10px] text-emerald-600/70 font-semibold uppercase tracking-wider mb-1">断裂类型</div>
                <div className="text-emerald-900 font-medium">
                  {result.fracture_type || '未知'}
                </div>
              </div>
              <div className="bg-white/80 p-3 rounded-lg border border-emerald-100/50">
                <div className="text-[10px] text-emerald-600/70 font-semibold uppercase tracking-wider mb-1">断裂位置</div>
                <div className="text-emerald-900 font-medium">
                  {result.location === 'inside_gauge' ? '标距内 (Inside Gauge)' : 
                   result.location === 'outside_gauge' ? '标距外 (Outside Gauge)' : 
                   result.location || '未知'}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (result.status === "no_fracture") {
    return (
      <div className="bg-amber-50 border-2 border-amber-200 rounded-xl p-5 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-full bg-amber-400 flex items-center justify-center shrink-0 shadow-md">
            <CheckCircle className="w-7 h-7 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-3 mb-1">
              <h3 className="text-xl font-bold text-amber-800">未发生断裂 (No Fracture)</h3>
              {overallConfidence != null && (
                <span className="px-2 py-0.5 bg-amber-100 text-amber-700 text-xs font-bold rounded-full border border-amber-200">
                  置信度: {(overallConfidence * 100).toFixed(0)}%
                </span>
              )}
            </div>
            <p className="text-sm text-amber-700 mt-2">Agent 已完成搜索，未能在视频中观察到样本断裂现象。</p>
          </div>
        </div>
      </div>
    );
  }

  if (result.status === "unrecognized") {
    return (
      <div className="bg-slate-50 border-2 border-slate-300 rounded-xl p-5 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="w-12 h-12 rounded-full bg-slate-300 flex items-center justify-center shrink-0 shadow-sm">
            <HelpCircle className="w-7 h-7 text-slate-600" />
          </div>
          <div>
            <h3 className="text-xl font-bold text-slate-800 mb-1">无法识别 (Unrecognized)</h3>
            <p className="text-sm text-slate-600 mt-2 bg-white p-3 rounded border border-slate-200">
              <span className="font-semibold text-slate-700">原因：</span> 
              {result.unrecognized_reason || "视觉信息不足或超出 Agent 识别能力。"}
            </p>
          </div>
        </div>
      </div>
    );
  }

  return null;
}
