import { useState } from "react";
import { Activity, ChevronDown, ChevronRight } from "lucide-react";
import type { AgentEvent } from "../api";
import RawEventLog from "./RawEventLog";
import LlmTransportTrace from "./LlmTransportTrace";

interface DiagnosticsPanelProps {
  taskId: string;
  events: AgentEvent[];
}

type DiagnosticsTab = "events" | "llm";

const TABS: { key: DiagnosticsTab; label: string }[] = [
  { key: "events", label: "原始事件" },
  { key: "llm", label: "模型传输" },
];

export default function DiagnosticsPanel({ taskId, events }: DiagnosticsPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [tab, setTab] = useState<DiagnosticsTab>("events");

  return (
    <div className="tech-panel overflow-hidden">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-2 text-left transition-colors hover:bg-slate-50"
      >
        <div className="flex items-center gap-2">
          <Activity className="h-3.5 w-3.5 text-slate-400" />
          <span className="tech-label">诊断信息</span>
          <span className="tech-label">{events.length} EVENTS · 含模型传输记录</span>
        </div>
        {expanded ? (
          <ChevronDown className="h-4 w-4 text-slate-400" />
        ) : (
          <ChevronRight className="h-4 w-4 text-slate-400" />
        )}
      </button>

      {expanded && (
        <div className="border-t border-slate-100">
          <div className="flex items-center gap-1 border-b border-slate-100 px-3 pt-2">
            {TABS.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => setTab(item.key)}
                className={`rounded-t-md border-b-2 px-3 py-1.5 text-xs transition-colors ${
                  tab === item.key
                    ? "border-[#002FA7] font-medium text-[#002FA7]"
                    : "border-transparent text-slate-400 hover:text-slate-600"
                }`}
              >
                {item.label}
              </button>
            ))}
          </div>
          <div className="max-h-[420px] overflow-auto p-3">
            {tab === "events" ? <RawEventLog events={events} /> : <LlmTransportTrace taskId={taskId} />}
          </div>
        </div>
      )}
    </div>
  );
}
