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
        <button onClick={onRefresh} className="flex items-center gap-2 px-3 py-1.5 bg-white border border-slate-200 rounded-md text-sm hover:border-[#002FA7]/40 hover:text-[#002FA7] text-slate-700 transition-colors">
          <RefreshCw className="w-4 h-4" /> 刷新
        </button>
      </div>
      <div className="bg-white border border-slate-200 shadow-sm rounded-md overflow-hidden">
        {config ? (
          <div>
            {/* 模型 */}
            <h3 className="px-4 pt-4 pb-2 tech-label">模型</h3>
            <div className="flex flex-col divide-y divide-slate-100">
              {/* 当前模型：唯一可点击行，保留箭头与 hover */}
              <button
                type="button"
                className={`flex w-full items-center justify-between p-4 text-left ${onReconfigure ? 'cursor-pointer hover:bg-slate-50' : ''} transition-colors`}
                onClick={onReconfigure}
                disabled={!onReconfigure}
                aria-label="切换决策模型"
              >
                <div className="min-w-0 pr-4">
                  <div className="text-slate-900 font-medium text-sm">当前模型</div>
                  <div className="text-slate-500 text-xs mt-1 truncate font-mono" title={config.active_model || "未配置"}>{config.active_model || "未配置"}</div>
                  {config.active_digest && <div className="mt-1 truncate font-mono text-[10px] text-slate-400" title={config.active_digest}>{config.active_digest.slice(0, 16)}…</div>}
                </div>
                {onReconfigure ? <ChevronRight className="w-4 h-4 text-slate-400 flex-shrink-0" /> : null}
              </button>

              <div className="flex items-center justify-between p-4">
                <div className="min-w-0 pr-4">
                  <div className="text-slate-900 font-medium text-sm">当前后端</div>
                  <div className="text-slate-500 text-xs mt-1 truncate font-mono">{config.active_backend}</div>
                </div>
              </div>

              <div className="flex items-center justify-between p-4">
                <div className="min-w-0 pr-4">
                  <div className="text-slate-900 font-medium text-sm">Mock 模式</div>
                  <div className={config.mock ? "text-amber-600 text-xs mt-1 font-medium font-mono" : "text-slate-500 text-xs mt-1 font-mono"}>{config.mock ? "开启" : "关闭"}</div>
                </div>
              </div>
            </div>

            {/* 运行环境 */}
            <h3 className="px-4 pt-4 pb-2 tech-label border-t border-slate-100">运行环境</h3>
            <div className="flex flex-col divide-y divide-slate-100">
              <div className="flex items-center justify-between p-4">
                <div className="min-w-0 pr-4">
                  <div className="text-slate-900 font-medium text-sm">Ollama</div>
                  <div className={`text-xs mt-1 font-mono ${config.ollama_ok ? "text-emerald-600" : "text-amber-600"}`}>{config.ollama_ok ? "已连接" : "未启动，请运行 ollama serve"}</div>
                </div>
                <span className={`h-2.5 w-2.5 rounded-full ${config.ollama_ok ? "bg-emerald-500" : "bg-amber-500"}`} />
              </div>

              <div className="flex items-center justify-between p-4">
                <div className="min-w-0 pr-4">
                  <div className="text-slate-900 font-medium text-sm">最大轮数</div>
                  <div className="text-slate-500 text-xs mt-1 font-mono">{config.max_rounds}</div>
                </div>
              </div>

              <div className="flex items-center justify-between p-4">
                <div className="min-w-0 pr-4">
                  <div className="text-slate-900 font-medium text-sm">运行时目录</div>
                  <div className="text-slate-500 text-xs mt-1 font-mono truncate" title={config.runtime_dir}>{config.runtime_dir}</div>
                </div>
              </div>
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
