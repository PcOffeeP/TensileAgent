import type { AgentEvent } from "../api";

interface RawEventLogProps {
  events: AgentEvent[];
}

export default function RawEventLog({ events }: RawEventLogProps) {
  if (events.length === 0) {
    return <div className="py-8 text-center text-xs text-slate-400">暂无事件，等待实时推送…</div>;
  }

  return (
    <div className="space-y-3 text-[11px] font-mono leading-relaxed">
      {events.map((ev, i) => (
        <div key={i} className="border-l-2 border-slate-200 py-1 pl-3">
          <div className="mb-1 flex items-center gap-2">
            <span className="font-medium text-[#002FA7]">{ev.event}</span>
            <span className="font-mono text-slate-400">
              {ev.timestamp ? new Date(ev.timestamp).toLocaleTimeString() : ""}
            </span>
          </div>
          <pre className="whitespace-pre-wrap break-all rounded-md border border-slate-200 bg-slate-50 p-2 font-mono text-[11px] text-slate-600">
            {JSON.stringify(ev.data, null, 2)}
          </pre>
        </div>
      ))}
    </div>
  );
}
