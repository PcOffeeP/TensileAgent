import { RefreshCw } from "lucide-react";
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
        <h2 className="text-xl font-bold">配置</h2>
        <button onClick={onRefresh} className="flex items-center gap-2 px-3 py-1.5 bg-gray-800 rounded text-sm hover:bg-gray-700">
          <RefreshCw className="w-4 h-4" /> 刷新
        </button>
      </div>
      <div className="bg-gray-900 rounded-lg p-4 space-y-3">
        {config ? (
          <>
            <div className="grid grid-cols-2 gap-4 text-sm">
              <div><span className="text-gray-500">Mock 模式</span><br /><span className={config.mock ? "text-yellow-400" : "text-gray-400"}>{config.mock ? "开启" : "关闭"}</span></div>
              <div><span className="text-gray-500">模型</span><br /><span>{config.model}</span></div>
              <div><span className="text-gray-500">最大轮数</span><br /><span>{config.max_rounds}</span></div>
              <div><span className="text-gray-500">配置文件</span><br /><span className="text-xs truncate">{config.config_path}</span></div>
            </div>
            <div className="text-sm">
              <span className="text-gray-500">运行时目录</span><br />
              <span className="text-xs">{config.runtime_dir}</span>
            </div>
            {onReconfigure && (
              <button
                onClick={onReconfigure}
                className="mt-4 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
              >
                修改决策模型
              </button>
            )}
          </>
        ) : (
          <p className="text-gray-500 text-sm">加载中...</p>
        )}
      </div>
    </div>
  );
}
