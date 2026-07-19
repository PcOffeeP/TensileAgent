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
        <div className="w-10 h-10 rounded-full bg-[#002FA7]/5 border border-[#002FA7]/10 flex items-center justify-center mb-3">
          <span className="inline-flex rounded-full h-2 w-2 bg-[#002FA7]/40"></span>
        </div>
        <p className="text-sm">等待 Agent 开始第一轮分析...</p>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col relative">
      <div className="px-5 py-2.5 border-b border-slate-200/70 bg-transparent sticky top-0 z-20 flex justify-between items-center">
        <h3 className="text-sm font-semibold text-slate-800">Agent 分析轨迹</h3>
        <span className="font-mono text-[11px] text-slate-400 tracking-wide">{rounds.length} ROUNDS</span>
      </div>

      <div
        ref={containerRef}
        className="flex-1 overflow-auto p-5 pr-4 custom-scrollbar"
      >
        <div className="max-w-3xl mx-auto pl-1">
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
