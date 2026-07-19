import { ChevronDown, ChevronUp, Bot, Scissors, FileCode2, AlertTriangle, ShieldAlert } from "lucide-react";
import { useState } from "react";
import type { AnalysisRound } from "../api";

interface RoundTraceCardProps {
  round: AnalysisRound;
  isActive?: boolean;
}

const sectionTitleClass = "tech-label";

export default function RoundTraceCard({ round, isActive = false }: RoundTraceCardProps) {
  const [expanded, setExpanded] = useState(isActive);

  const isError = !!round.validationError || (round.terminationRequest && !round.terminationRequest.allowed);
  const isTerminated = round.terminationRequest?.allowed;

  return (
    <div className={`relative flex gap-3.5 ${isActive ? "" : "opacity-75 hover:opacity-100"} transition-opacity`}>
      {/* Timeline connector & icon */}
      <div className="flex flex-col items-center">
        <div className={`w-7 h-7 rounded-full flex items-center justify-center shrink-0 z-10 border
          ${isTerminated ? "bg-emerald-50 border-emerald-500 text-emerald-600" :
            isError ? "bg-rose-50 border-rose-500 text-rose-600" :
            isActive ? "bg-[#002FA7]/10 border-[#002FA7] text-[#002FA7]" :
            "bg-white border-slate-300 text-slate-400"}`}
        >
          {isTerminated ? <ShieldAlert className="w-3.5 h-3.5" /> :
           isError ? <AlertTriangle className="w-3.5 h-3.5" /> :
           <Bot className="w-3.5 h-3.5" />}
        </div>
        <div className="w-px flex-1 border-l border-dashed border-slate-300 my-1"></div>
      </div>

      {/* Card Content */}
      <div className={`flex-1 rounded-lg border mb-5 overflow-hidden transition-colors
        ${isActive ? "border-[#002FA7]/40 bg-white shadow-sm" : "border-slate-200/80 bg-white/60"}`}
      >
        {/* Header (Always visible) */}
        <div
          className="px-4 py-2.5 cursor-pointer flex items-center justify-between gap-3 hover:bg-slate-50/60 transition-colors"
          onClick={() => setExpanded(!expanded)}
        >
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="text-sm font-semibold text-slate-700 shrink-0">第 <span className="font-mono">{round.displayRound}</span> 轮</span>
            {round.toolCall?.name && (
              <span className="tech-chip flex items-center gap-1">
                <FileCode2 className="w-3 h-3" />
                {round.toolCall.name}
              </span>
            )}
            {round.sampleRange && (
              <span className="font-mono text-[11px] text-slate-500 flex items-center gap-1">
                <Scissors className="w-3 h-3" />
                采样 {round.sampleRange[0]}s–{round.sampleRange[1]}s
              </span>
            )}
          </div>
          <div className="flex items-center gap-2.5 shrink-0">
            {round.confidenceLevel && (
              <span className={`text-[11px] px-2 py-0.5 rounded-full border
                ${round.confidenceLevel === "高" ? "bg-emerald-50/80 text-emerald-600 border-emerald-200/80" :
                  round.confidenceLevel === "中" ? "bg-amber-50/80 text-amber-600 border-amber-200/80" :
                  "bg-rose-50/80 text-rose-600 border-rose-200/80"}`}
              >
                置信度 {round.confidenceLevel}
              </span>
            )}
            {expanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
          </div>
        </div>

        {/* Expanded Details */}
        {expanded && (
          <div className="px-4 pb-4 pt-3 border-t border-slate-100 flex flex-col gap-3">
            {/* Reasoning */}
            {round.toolCall?.reasoning && (
              <div className="flex flex-col gap-1.5">
                <span className={sectionTitleClass}>思考过程</span>
                <div className="bg-slate-50/70 border border-slate-100 rounded-md p-2.5 text-xs leading-relaxed text-slate-600">
                  {round.toolCall.reasoning}
                </div>
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {/* Output Summary */}
              {round.modelOutput && (
                <div className="flex flex-col gap-1.5">
                  <span className={sectionTitleClass}>模型输出</span>
                  <div className="bg-white border border-slate-200/80 rounded-md p-2.5 text-xs text-slate-700 space-y-1">
                    <div className="flex items-center gap-1.5">
                      <span className="text-slate-400">是否断裂</span>
                      <span className="font-mono">{String(round.modelOutput.has_fracture)}</span>
                    </div>
                    {round.modelOutput.has_fracture && (
                      <>
                        <div className="flex items-center gap-1.5">
                          <span className="text-slate-400">断裂区间</span>
                          <span className="font-mono">{JSON.stringify(round.modelOutput.fracture_between)}</span>
                        </div>
                        {round.modelOutput.type && (
                          <div className="flex items-center gap-1.5">
                            <span className="text-slate-400">类型</span>
                            <span>{round.modelOutput.type}</span>
                          </div>
                        )}
                      </>
                    )}
                  </div>
                </div>
              )}

              {/* State & Candidate changes */}
              <div className="flex flex-col gap-1.5">
                <span className={sectionTitleClass}>状态转换</span>
                <div className="bg-white border border-slate-200/80 rounded-md p-2.5 text-xs text-slate-700 space-y-1.5">
                  {round.previousState && round.nextState && (
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-slate-400">状态</span>
                      <span className="font-mono bg-slate-100 px-1 rounded">{round.previousState}</span>
                      <span className="text-slate-300">→</span>
                      <span className="font-mono bg-[#002FA7]/10 text-[#002FA7] px-1 rounded">{round.nextState}</span>
                    </div>
                  )}
                  {round.previousCandidate && round.nextCandidate && (
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-slate-400">候选区间</span>
                      <span className="font-mono bg-slate-100 px-1 rounded">{JSON.stringify(round.previousCandidate)}</span>
                      <span className="text-slate-300">→</span>
                      <span className="font-mono bg-amber-100 text-amber-700 px-1 rounded">{JSON.stringify(round.nextCandidate)}</span>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Validation Error */}
            {round.validationError && (
              <div className="bg-rose-50/70 border border-rose-200/70 p-2 rounded-md text-[11px] text-rose-700 flex items-start gap-1.5">
                <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold block mb-0.5">参数校验警告</span>
                  {round.validationError.message || JSON.stringify(round.validationError)}
                </div>
              </div>
            )}

            {/* Termination Request */}
            {round.terminationRequest && (
              <div className={`p-2 rounded-md text-[11px] flex items-start gap-1.5 border
                ${round.terminationRequest.allowed ? "bg-emerald-50/70 border-emerald-200/70 text-emerald-700" : "bg-amber-50/70 border-amber-200/70 text-amber-700"}`}
              >
                <ShieldAlert className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold block mb-0.5">
                    {round.terminationRequest.allowed ? "终止请求通过" : "终止请求被拒绝"}
                  </span>
                  {round.terminationRequest.reason}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
