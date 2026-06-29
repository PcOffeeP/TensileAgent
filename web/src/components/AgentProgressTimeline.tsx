import { useEffect, useRef } from "react";
import type { AnalysisRound } from "../api";
import RoundTraceCard from "./RoundTraceCard";

interface AgentProgressTimelineProps {
  rounds: AnalysisRound[];
}

export default function AgentProgressTimeline({ rounds }: AgentProgressTimelineProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom when new rounds are added
  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [rounds.length]);

  if (rounds.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center p-8 text-slate-400">
        <div className="w-12 h-12 rounded-full bg-slate-50 flex items-center justify-center mb-3 border border-slate-100">
          <span className="relative flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#002FA7] opacity-20"></span>
            <span className="relative inline-flex rounded-full h-3 w-3 bg-[#002FA7]/40"></span>
          </span>
        </div>
        <p className="text-sm">等待 Agent 开始第一轮分析...</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col relative bg-slate-50/30">
      <div className="px-5 py-3 border-b border-slate-200 bg-white/80 backdrop-blur sticky top-0 z-20 flex justify-between items-center shadow-[0_1px_2px_rgba(0,0,0,0.02)]">
        <h3 className="text-sm font-semibold text-slate-800">Agent 分析轨迹</h3>
        <span className="text-xs text-slate-500">{rounds.length} 轮已记录</span>
      </div>
      
      <div 
        ref={containerRef}
        className="flex-1 overflow-auto p-6 pr-4 custom-scrollbar"
      >
        <div className="max-w-3xl mx-auto pl-2">
          {rounds.map((round, idx) => (
            <RoundTraceCard 
              key={round.round} 
              round={round} 
              isActive={idx === rounds.length - 1} 
            />
          ))}
        </div>
      </div>
    </div>
  );
}
