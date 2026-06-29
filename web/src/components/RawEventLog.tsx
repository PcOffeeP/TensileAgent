import { useState } from "react";
import { Terminal, ChevronRight, ChevronDown } from "lucide-react";
import type { AgentEvent } from "../api";

interface RawEventLogProps {
  events: AgentEvent[];
}

export default function RawEventLog({ events }: RawEventLogProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="h-full flex flex-col bg-slate-900 rounded-xl overflow-hidden shadow-inner border border-slate-800">
      <div 
        className="px-4 py-3 bg-slate-800/80 border-b border-slate-700/50 flex items-center justify-between cursor-pointer hover:bg-slate-800 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <Terminal className="w-4 h-4 text-slate-400" />
          <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-widest">Diagnostic Log</h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-slate-500 font-mono">{events.length} events</span>
          {expanded ? <ChevronDown className="w-4 h-4 text-slate-400" /> : <ChevronRight className="w-4 h-4 text-slate-400" />}
        </div>
      </div>
      
      {expanded ? (
        <div className="flex-1 overflow-auto p-4 custom-scrollbar text-[11px] font-mono leading-relaxed">
          {events.length === 0 ? (
            <div className="text-slate-600 text-center mt-4">Waiting for events...</div>
          ) : (
            <div className="space-y-3">
              {events.map((ev, i) => (
                <div key={i} className="border-l-2 border-slate-700 pl-3 py-1">
                  <div className="flex items-center gap-2 mb-1 opacity-70">
                    <span className="text-emerald-400">{ev.event}</span>
                    <span className="text-slate-500">{ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString() : ''}</span>
                  </div>
                  <pre className="text-slate-300 whitespace-pre-wrap break-all bg-slate-800/50 p-2 rounded">
                    {JSON.stringify(ev.data, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="p-4 text-[10px] text-slate-500 italic text-center opacity-60">
          Click header to expand raw event JSON logs.
        </div>
      )}
    </div>
  );
}
