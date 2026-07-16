import { RefreshCw, ChevronRight } from "lucide-react";
import type { AppConfig } from "../api";

interface ConfigViewProps {
  config: AppConfig | null;
  onRefresh: () => void;
  onReconfigure?: () => void;
}

export default function ConfigView({ config, onRefresh, onReconfigure }: ConfigViewProps) {
  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-bold text-slate-900">配置</h2>
        <button onClick={onRefresh} className="flex items-center gap-2 px-3 py-1.5 bg-slate-100 rounded text-sm hover:bg-slate-200 text-slate-800 transition-colors">
          <RefreshCw className="w-4 h-4" /> 刷新
        </button>
      </div>
      <div className="bg-white border border-slate-200 shadow-sm rounded-lg overflow-hidden">
        {config ? (
          <div className="flex flex-col divide-y divide-slate-100">
            {/* 模型配置 */}
            <button
              type="button"
              className={`flex w-full items-center justify-between p-4 text-left ${onReconfigure ? 'cursor-pointer hover:bg-slate-50' : ''} transition-colors`}
              onClick={onReconfigure}
              disabled={!onReconfigure}
              aria-label="切换决策模型"
            >
              <div className="min-w-0 pr-4">
                <div className="text-slate-900 font-medium text-sm">当前模型</div>
                <div className="text-slate-500 text-xs mt-1 truncate" title={config.active_model || "未配置"}>{config.active_model || "未配置"}</div>
                {config.active_digest && <div className="mt-1 truncate font-mono text-[10px] text-slate-400" title={config.active_digest}>{config.active_digest.slice(0, 16)}…</div>}
              </div>
              {onReconfigure ? <ChevronRight className="w-4 h-4 text-slate-400 flex-shrink-0" /> : <div className="w-4 h-4" />}
            </button>

            {/* 其他配置项 */}
            <div className="flex items-center justify-between p-4 cursor-pointer hover:bg-slate-50 transition-colors">
              <div className="min-w-0 pr-4">
                <div className="text-slate-900 font-medium text-sm">当前后端</div>
                <div className="text-slate-500 text-xs mt-1 truncate">{config.active_backend}</div>
              </div>
              <ChevronRight className="w-4 h-4 text-slate-400 flex-shrink-0" />
            </div>

            <div className="flex items-center justify-between p-4">
              <div className="min-w-0 pr-4">
                <div className="text-slate-900 font-medium text-sm">Ollama</div>
                <div className={`text-xs mt-1 ${config.ollama_ok ? "text-emerald-600" : "text-amber-600"}`}>{config.ollama_ok ? "已连接" : "未启动，请运行 ollama serve"}</div>
              </div>
              <span className={`h-2.5 w-2.5 rounded-full ${config.ollama_ok ? "bg-emerald-500" : "bg-amber-500"}`} />
            </div>

            <div className="flex items-center justify-between p-4 cursor-pointer hover:bg-slate-50 transition-colors">
              <div className="min-w-0 pr-4">
                <div className="text-slate-900 font-medium text-sm">Mock 模式</div>
                <div className={config.mock ? "text-amber-600 text-xs mt-1 font-medium" : "text-slate-500 text-xs mt-1"}>{config.mock ? "开启" : "关闭"}</div>
              </div>
              <ChevronRight className="w-4 h-4 text-slate-400 flex-shrink-0" />
            </div>

            <div className="flex items-center justify-between p-4 cursor-pointer hover:bg-slate-50 transition-colors">
              <div className="min-w-0 pr-4">
                <div className="text-slate-900 font-medium text-sm">最大轮数</div>
                <div className="text-slate-500 text-xs mt-1">{config.max_rounds}</div>
              </div>
              <ChevronRight className="w-4 h-4 text-slate-400 flex-shrink-0" />
            </div>

            <div className="flex items-center justify-between p-4 cursor-pointer hover:bg-slate-50 transition-colors">
              <div className="min-w-0 pr-4">
                <div className="text-slate-900 font-medium text-sm">运行时目录</div>
                <div className="text-slate-500 text-xs mt-1 font-mono truncate" title={config.runtime_dir}>{config.runtime_dir}</div>
              </div>
              <ChevronRight className="w-4 h-4 text-slate-400 flex-shrink-0" />
            </div>
          </div>
        ) : (
          <div className="p-4">
            <p className="text-slate-500 text-sm">加载中...</p>
          </div>
        )}
      </div>
    </div>
  );
}
