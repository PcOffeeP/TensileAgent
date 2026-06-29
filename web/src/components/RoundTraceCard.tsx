import { ChevronDown, ChevronUp, Bot, Scissors, FileCode2, AlertTriangle, ShieldAlert } from "lucide-react";
import { useState } from "react";
import type { AnalysisRound } from "../api";

interface RoundTraceCardProps {
  round: AnalysisRound;
  isActive?: boolean;
}

export default function RoundTraceCard({ round, isActive = false }: RoundTraceCardProps) {
  const [expanded, setExpanded] = useState(isActive);

  const isError = !!round.validationError || (round.terminationRequest && !round.terminationRequest.allowed);
  const isTerminated = round.terminationRequest?.allowed;

  return (
    <div className={`relative flex gap-4 ${isActive ? 'opacity-100' : 'opacity-80 hover:opacity-100'} transition-opacity`}>
      {/* Timeline connector & icon */}
      <div className="flex flex-col items-center">
        <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 z-10 border-2 
          ${isTerminated ? 'bg-emerald-100 border-emerald-500 text-emerald-600' : 
            isError ? 'bg-rose-100 border-rose-500 text-rose-600' : 
            isActive ? 'bg-[#002FA7]/10 border-[#002FA7] text-[#002FA7] shadow-[0_0_10px_rgba(0,47,167,0.2)]' : 
            'bg-slate-100 border-slate-300 text-slate-500'}`}
        >
          {isTerminated ? <ShieldAlert className="w-4 h-4" /> : 
           isError ? <AlertTriangle className="w-4 h-4" /> : 
           <Bot className="w-4 h-4" />}
        </div>
        <div className="w-px flex-1 bg-slate-200 my-1"></div>
      </div>

      {/* Card Content */}
      <div className={`flex-1 glass-panel rounded-xl border mb-6 shadow-sm overflow-hidden transition-all
        ${isActive ? 'border-[#002FA7]/30 ring-1 ring-[#002FA7]/10 bg-white/90' : 'border-slate-200 bg-white/60'}`}
      >
        {/* Header (Always visible) */}
        <div 
          className="px-4 py-3 cursor-pointer flex items-center justify-between hover:bg-slate-50/50 transition-colors"
          onClick={() => setExpanded(!expanded)}
        >
          <div className="flex items-center gap-3">
            <span className="text-sm font-bold text-slate-700">第 {round.displayRound} 轮</span>
            {round.toolCall?.name && (
              <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-slate-100 text-slate-600 border border-slate-200 flex items-center gap-1">
                <FileCode2 className="w-3 h-3" />
                {round.toolCall.name}
              </span>
            )}
            {round.sampleRange && (
              <span className="text-xs text-slate-500 flex items-center gap-1">
                <Scissors className="w-3 h-3" />
                采样: {round.sampleRange[0]}s - {round.sampleRange[1]}s
              </span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {round.confidenceLevel && (
              <span className={`text-[11px] px-2 py-0.5 rounded-full border
                ${round.confidenceLevel === '高' ? 'bg-emerald-50 text-emerald-600 border-emerald-200' :
                  round.confidenceLevel === '中' ? 'bg-amber-50 text-amber-600 border-amber-200' :
                  'bg-rose-50 text-rose-600 border-rose-200'}`}
              >
                置信度: {round.confidenceLevel}
              </span>
            )}
            {expanded ? <ChevronUp className="w-4 h-4 text-slate-400" /> : <ChevronDown className="w-4 h-4 text-slate-400" />}
          </div>
        </div>

        {/* Expanded Details */}
        {expanded && (
          <div className="px-4 pb-4 border-t border-slate-100 pt-3 flex flex-col gap-3 text-sm">
            {/* Reasoning */}
            {round.toolCall?.reasoning && (
              <div className="bg-slate-50 p-3 rounded-lg border border-slate-100 text-slate-600 text-xs leading-relaxed">
                <span className="font-semibold text-slate-700 mr-2">思考过程 (Reasoning):</span>
                {round.toolCall.reasoning}
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-1">
              {/* Output Summary */}
              {round.modelOutput && (
                <div className="flex flex-col gap-1.5">
                  <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">模型输出 (Model Output)</span>
                  <div className="bg-white border border-slate-200 rounded p-2 text-xs text-slate-700">
                    <div><span className="text-slate-400">是否断裂 (has_fracture):</span> {String(round.modelOutput.has_fracture)}</div>
                    {round.modelOutput.has_fracture && (
                      <>
                        <div><span className="text-slate-400">断裂区间 (between):</span> {JSON.stringify(round.modelOutput.fracture_between)}</div>
                        {round.modelOutput.type && <div><span className="text-slate-400">类型 (type):</span> {round.modelOutput.type}</div>}
                      </>
                    )}
                  </div>
                </div>
              )}

              {/* State & Candidate changes */}
              <div className="flex flex-col gap-1.5">
                <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">状态转换 (State Transition)</span>
                <div className="bg-white border border-slate-200 rounded p-2 text-xs text-slate-700 space-y-1">
                  {round.previousState && round.nextState && (
                    <div className="flex items-center gap-2">
                      <span className="text-slate-400">状态 (state):</span>
                      <span className="font-mono bg-slate-100 px-1 rounded">{round.previousState}</span>
                      →
                      <span className="font-mono bg-[#002FA7]/10 text-[#002FA7] px-1 rounded">{round.nextState}</span>
                    </div>
                  )}
                  {round.previousCandidate && round.nextCandidate && (
                    <div className="flex items-center gap-2">
                      <span className="text-slate-400">候选 (candidate):</span>
                      <span className="font-mono bg-slate-100 px-1 rounded">{JSON.stringify(round.previousCandidate)}</span>
                      →
                      <span className="font-mono bg-amber-100 text-amber-700 px-1 rounded">{JSON.stringify(round.nextCandidate)}</span>
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* Validation Error */}
            {round.validationError && (
              <div className="bg-rose-50 border border-rose-200 p-2.5 rounded-lg text-xs text-rose-700 flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold block mb-0.5">参数校验警告 (Validation Error)</span>
                  {round.validationError.message || JSON.stringify(round.validationError)}
                </div>
              </div>
            )}

            {/* Termination Request */}
            {round.terminationRequest && (
              <div className={`p-2.5 rounded-lg text-xs flex items-start gap-2 border 
                ${round.terminationRequest.allowed ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-amber-50 border-amber-200 text-amber-700'}`}
              >
                <ShieldAlert className="w-4 h-4 shrink-0 mt-0.5" />
                <div>
                  <span className="font-semibold block mb-0.5">
                    {round.terminationRequest.allowed ? '终止请求通过 (Accepted)' : '终止请求被拒绝 (Rejected)'}
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
