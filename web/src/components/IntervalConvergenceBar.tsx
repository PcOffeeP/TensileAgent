import type { AnalysisTrace, AnalysisRound, FinalResult } from "../api";

interface IntervalConvergenceBarProps {
  trace: AnalysisTrace;
  fallbackResult?: FinalResult | null;
}

export default function IntervalConvergenceBar({ trace, fallbackResult }: IntervalConvergenceBarProps) {
  const duration = trace.videoDurationSec;

  if (!duration) return null;

  const getPercent = (time: number) => Math.max(0, Math.min(100, (time / duration) * 100));

  // Find the latest candidate from rounds, or initial
  let currentCandidate = trace.initialCandidate;
  for (const r of trace.rounds) {
    if (r.nextCandidate) currentCandidate = r.nextCandidate;
    else if (r.candidateAtStart) currentCandidate = r.candidateAtStart;
  }

  // Find final result time_range
  const finalResult = trace.finalResult ?? fallbackResult;
  const isFracture = finalResult?.status === "fracture";
  const finalRange = isFracture ? finalResult?.time_range : null;

  return (
    <div className="tech-panel px-4 py-3 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-800 flex items-center gap-2">
          区间收敛跟踪
          <span className="tech-label">CONVERGENCE</span>
        </h3>
        <span className="text-xs font-mono text-slate-500">
          0.00s ~ {duration.toFixed(2)}s
        </span>
      </div>

      <div className="relative h-10 bg-slate-100 rounded-md overflow-hidden border border-slate-200">
        {/* Previous sample ranges (Light color) */}
        {trace.rounds.map((r, i) => {
          if (!r.sampleRange) return null;
          const [start, end] = r.sampleRange;
          const left = getPercent(start);
          const width = getPercent(end) - left;
          return (
            <div
              key={`sample-${i}`}
              className="absolute top-0 bottom-0 bg-[#002FA7]/10 border-l border-r border-[#002FA7]/20"
              style={{ left: `${left}%`, width: `${width}%` }}
              title={`Round ${r.displayRound} Sample: ${start}s - ${end}s`}
            />
          );
        })}

        {/* Current Candidate (Strong color, slightly transparent) */}
        {currentCandidate && !finalRange && (
          <div
            className="absolute top-1 bottom-1 bg-amber-400/30 border-2 border-amber-500 rounded-md shadow-sm"
            style={{
              left: `${getPercent(currentCandidate[0])}%`,
              width: `${getPercent(currentCandidate[1]) - getPercent(currentCandidate[0])}%`
            }}
          >
            <div className="absolute -top-6 left-1/2 -translate-x-1/2 bg-amber-500 text-white text-[10px] px-1.5 py-0.5 rounded font-mono whitespace-nowrap shadow-sm">
              Candidate
            </div>
          </div>
        )}

        {/* Final Range Marker */}
        {finalRange && (
          <div
            className="absolute top-0 bottom-0 bg-rose-500 border-2 border-rose-600 rounded-md shadow-md z-10"
            style={{
              left: `${getPercent(finalRange[0])}%`,
              width: `${Math.max(0.5, getPercent(finalRange[1]) - getPercent(finalRange[0]))}%`
            }}
          >
            <div className="absolute -top-7 left-1/2 -translate-x-1/2 bg-rose-600 text-white text-[10px] px-2 py-0.5 rounded font-mono whitespace-nowrap shadow-sm font-bold">
              Fracture!
            </div>
          </div>
        )}
      </div>

      {/* Scale ruler: 0 / 25 / 50 / 75 / 100% of duration */}
      <div className="flex justify-between -mt-1.5">
        {[0, 25, 50, 75, 100].map((p) => (
          <div
            key={p}
            className={`flex flex-col gap-0.5 ${p === 0 ? "items-start" : p === 100 ? "items-end" : "items-center"}`}
          >
            <div className="w-px h-1 bg-slate-300" />
            <span className="font-mono text-[9px] leading-none text-slate-400">
              {(duration * (p / 100)).toFixed(2)}s
            </span>
          </div>
        ))}
      </div>

      <div className="flex items-center gap-3 font-mono text-[10px] text-slate-400 justify-end">
        <div className="flex items-center gap-1">
          <div className="w-2.5 h-2.5 bg-[#002FA7]/10 border border-[#002FA7]/20 rounded-sm"></div>
          <span>历史采样</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-2.5 h-2.5 bg-amber-400/30 border-2 border-amber-500 rounded-sm"></div>
          <span>当前候选</span>
        </div>
        <div className="flex items-center gap-1">
          <div className="w-2.5 h-2.5 bg-rose-500 border-2 border-rose-600 rounded-sm"></div>
          <span>最终断裂</span>
        </div>
      </div>
    </div>
  );
}
