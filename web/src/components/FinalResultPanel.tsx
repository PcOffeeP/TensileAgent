import { CheckCircle, AlertCircle, HelpCircle, XCircle } from "lucide-react";
import type { FinalResult } from "../api";

interface FinalResultPanelProps {
  result: FinalResult | null;
  error: { stage?: string; code?: string; message: string } | null;
  response?: {
    status: "answered" | "partial" | "unrecognized" | "failed";
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
    const errorMeta = [
      error.stage ? `Stage: ${error.stage}` : null,
      error.code ? `Code: ${error.code}` : null,
      (error as any).error && !error.code ? `Error: ${(error as any).error}` : null,
    ]
      .filter(Boolean)
      .join(" · ");
    return (
      <div className="tech-corners bg-white border border-slate-200 border-l-[3px] border-l-rose-500 rounded-lg p-4 shadow-sm">
        <div className="flex items-start gap-3">
          <div className="w-8 h-8 rounded-md border border-rose-200 bg-rose-50/60 flex items-center justify-center shrink-0">
            <XCircle className="w-4 h-4 text-rose-500" />
          </div>
          <div className="min-w-0">
            <div className="tech-label mb-1">ERROR</div>
            <h3 className="text-sm font-semibold text-slate-800">分析任务失败</h3>
            <p className="text-sm text-slate-600 mt-1">{error.message ?? "Unknown error"}</p>
            {errorMeta && <p className="font-mono text-[10px] text-slate-400 mt-1.5">{errorMeta}</p>}
          </div>
        </div>
      </div>
    );
  }

  if (!result) return null;

  if ((response?.status === "answered" || response?.status === "partial") && response.answer) {
    const footnote = [
      result.visual_evidence?.status === "available"
        ? "视觉依据为 experimental，尚未完成反事实可靠性验收"
        : null,
      result.confidence
        ? `Confidence 数值尚未校准，当前仅展示证据等级 ${result.confidence.evidence_level}`
        : null,
    ]
      .filter(Boolean)
      .join("；");
    return (
      <div className="tech-corners bg-white border border-slate-200 border-l-[3px] border-l-[#002FA7] rounded-lg p-5 shadow-sm">
        <div className="tech-label mb-1">{response.status === "partial" ? "PARTIAL ANSWER" : "ANSWER"}</div>
        <h3 className="text-lg font-bold text-slate-900 mb-2">
          {response.status === "partial" ? "部分分析回答" : "分析回答"}
        </h3>
        {response.status === "partial" && (
          <p className="text-xs text-amber-600 mb-3">
            部分次要字段因证据不足暂不可用。
          </p>
        )}
        <div className="space-y-3">
          {Object.entries(response.answer).map(([key, value]) => (
            <div key={key} className="flex gap-4 border-b border-slate-100 pb-3 last:border-0 last:pb-0">
              <span className="tech-label w-24 shrink-0 pt-0.5">{FIELD_LABELS[key] ?? key}</span>
              <span className={`text-sm text-slate-900 ${key === "visual_evidence" ? "" : "font-mono"}`}>
                {formatAnswerValue(key, value)}
              </span>
            </div>
          ))}
        </div>
        {footnote && (
          <p className="mt-4 text-[11px] text-slate-400">{footnote}。</p>
        )}
      </div>
    );
  }

  if (result.status === "fracture") {
    return (
      <div className="tech-corners bg-white border border-slate-200 border-l-[3px] border-l-emerald-500 rounded-lg p-5 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="w-9 h-9 rounded-md border border-emerald-200 bg-emerald-50/60 flex items-center justify-center shrink-0">
            <CheckCircle className="w-5 h-5 text-emerald-600" />
          </div>
          <div className="flex-1">
            <div className="tech-label mb-1">DIAGNOSIS</div>
            <div className="flex items-center gap-3 mb-2 flex-wrap">
              <h3 className="text-lg font-bold text-slate-900">
                发现断裂 <span className="font-mono text-xs text-emerald-600 tracking-wider">FRACTURE</span>
              </h3>
              {overallConfidence != null && (
                <span className="tech-chip">
                  置信度 {(overallConfidence * 100).toFixed(0)}%
                </span>
              )}
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
              <div className="bg-slate-50/60 p-3 rounded-md border border-slate-200">
                <div className="tech-label mb-1">断裂时间区间</div>
                <div className="text-slate-900 font-mono text-sm font-medium">
                  {result.time_range ? `${result.time_range[0]}s - ${result.time_range[1]}s` : '未知'}
                </div>
              </div>
              <div className="bg-slate-50/60 p-3 rounded-md border border-slate-200">
                <div className="tech-label mb-1">断裂类型</div>
                <div className="text-slate-900 font-mono text-sm font-medium">
                  {result.fracture_type || '未知'}
                </div>
              </div>
              <div className="bg-slate-50/60 p-3 rounded-md border border-slate-200">
                <div className="tech-label mb-1">断裂位置</div>
                <div className="text-slate-900 font-mono text-sm font-medium">
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
      <div className="tech-corners bg-white border border-slate-200 border-l-[3px] border-l-amber-500 rounded-lg p-5 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="w-9 h-9 rounded-md border border-amber-200 bg-amber-50/60 flex items-center justify-center shrink-0">
            <CheckCircle className="w-5 h-5 text-amber-600" />
          </div>
          <div>
            <div className="tech-label mb-1">DIAGNOSIS</div>
            <div className="flex items-center gap-3 mb-1 flex-wrap">
              <h3 className="text-lg font-bold text-slate-900">
                未发生断裂 <span className="font-mono text-xs text-amber-600 tracking-wider">NO FRACTURE</span>
              </h3>
              {overallConfidence != null && (
                <span className="tech-chip">
                  置信度 {(overallConfidence * 100).toFixed(0)}%
                </span>
              )}
            </div>
            <p className="text-sm text-slate-600 mt-2">Agent 已完成搜索，未能在视频中观察到样本断裂现象。</p>
          </div>
        </div>
      </div>
    );
  }

  if (result.status === "unrecognized") {
    return (
      <div className="tech-corners bg-white border border-slate-200 border-l-[3px] border-l-slate-400 rounded-lg p-5 shadow-sm">
        <div className="flex items-start gap-4">
          <div className="w-9 h-9 rounded-md border border-slate-200 bg-slate-50 flex items-center justify-center shrink-0">
            <HelpCircle className="w-5 h-5 text-slate-500" />
          </div>
          <div>
            <div className="tech-label mb-1">DIAGNOSIS</div>
            <h3 className="text-lg font-bold text-slate-900 mb-1">
              无法识别 <span className="font-mono text-xs text-slate-500 tracking-wider">UNRECOGNIZED</span>
            </h3>
            <p className="text-sm text-slate-600 mt-2 bg-slate-50/60 p-3 rounded-md border border-slate-200">
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
