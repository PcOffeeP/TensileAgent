import { useEffect, useRef, useState } from "react";
import {
  activateDecisionModel,
  getConfigStatus,
  listDecisionModels,
  setupConfig,
  testDecisionModel,
  type ConfigStatus,
  type ModelOption,
} from "../api";

interface SetupDialogProps {
  onComplete: () => void;
  mode?: "setup" | "reconfigure";
}

export default function SetupDialog({ onComplete, mode = "setup" }: SetupDialogProps) {
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;
  const [status, setStatus] = useState<ConfigStatus | null>(null);
  const [backend, setBackend] = useState<"local" | "remote">("local");
  const [models, setModels] = useState<ModelOption[]>([]);
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [reasoning, setReasoning] = useState("none");
  const [busy, setBusy] = useState(true);
  const [message, setMessage] = useState("");

  useEffect(() => {
    getConfigStatus()
      .then((value) => {
        setStatus(value);
        const selected = value.active_backend === "remote" ? "remote" : "local";
        setBackend(selected);
        setModel(selected === "local" ? value.local.current_model || "" : value.remote.current_model || "");
        setReasoning(value.local.reasoning_effort || "none");
        if (mode === "setup" && value.configured) onCompleteRef.current();
      })
      .catch((error) => setMessage(error.message || "读取配置失败"))
      .finally(() => setBusy(false));
  }, [mode]);

  useEffect(() => {
    setMessage("");
    listDecisionModels(backend)
      .then((result) => {
        setModels(result.models || []);
        if (!model && result.models.length > 0) setModel(result.models[0].id);
        if (!result.ok && result.warning) setMessage(result.warning);
      })
      .catch((error) => setMessage(error.message || "获取模型列表失败"));
  }, [backend]);

  async function save() {
    if (!model.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      if (backend === "remote" && !status?.remote.has_api_key) {
        if (!apiKey.trim()) throw new Error("远程后端需要百炼 API Key");
        await setupConfig(apiKey, model, "setup");
      } else {
        await testDecisionModel(backend, model);
        await activateDecisionModel(backend, model, reasoning);
      }
      onComplete();
    } catch (error: any) {
      setMessage(error.message || "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function refreshModelList() {
    setBusy(true);
    setMessage("");
    try {
      const result = await listDecisionModels(backend);
      setModels(result.models || []);
      if (!model && result.models.length > 0) setModel(result.models[0].id);
      setMessage(result.ok ? "模型列表已刷新" : result.warning || "获取模型列表失败");
    } catch (error: any) {
      setMessage(error.message || "获取模型列表失败");
    } finally {
      setBusy(false);
    }
  }

  async function testOnly() {
    if (!model.trim()) return;
    setBusy(true);
    setMessage("");
    try {
      if (backend === "remote" && !status?.remote.has_api_key) {
        if (!apiKey.trim()) throw new Error("远程后端需要百炼 API Key");
        const result = await setupConfig(apiKey, "__test__", "test");
        if (!result.ok) throw new Error(result.warning || "远程连接测试失败");
      } else {
        await testDecisionModel(backend, model);
      }
      setMessage("连接测试成功，未修改当前配置");
    } catch (error: any) {
      setMessage(error.message || "连接测试失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-[min(560px,92vw)] rounded-2xl border border-slate-200 bg-white p-8 shadow-2xl">
        <h2 className="text-xl font-bold text-slate-900">{mode === "setup" ? "配置决策模型" : "切换决策模型"}</h2>
        <p className="mt-2 text-sm text-slate-500">默认使用本地模型；远程模型只会在你手动选择后启用。</p>

        <div className="mt-6 grid grid-cols-2 gap-3">
          {(["local", "remote"] as const).map((value) => (
            <button
              key={value}
              onClick={() => {
                setBackend(value);
                setModel(value === "local" ? status?.local.current_model || "" : status?.remote.current_model || "");
              }}
              className={`rounded-lg border px-4 py-3 text-sm font-medium ${backend === value ? "border-blue-700 bg-blue-50 text-blue-800" : "border-slate-200 text-slate-600"}`}
            >
              {value === "local" ? "本地 Ollama" : "远程百炼"}
            </button>
          ))}
        </div>

        {backend === "local" && status?.local.service_ok === false && (
          <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
            Ollama 未启动。请在终端运行 <code className="font-mono">ollama serve</code> 后刷新。
          </div>
        )}

        {backend === "remote" && !status?.remote.has_api_key && (
          <div className="mt-4">
            <label className="text-xs font-semibold text-slate-600">百炼 API Key</label>
            <input type="password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="sk-..." className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />
          </div>
        )}

        <div className="mt-4">
          <label className="text-xs font-semibold text-slate-600">模型</label>
          <select value={model} onChange={(event) => setModel(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
            <option value="">请选择模型</option>
            {models.map((item) => <option key={item.id} value={item.id}>{item.id}</option>)}
          </select>
          {models.length === 0 && <input value={model} onChange={(event) => setModel(event.target.value)} placeholder="手动输入模型名" className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm" />}
        </div>

        {backend === "local" && (
          <div className="mt-4">
            <label className="text-xs font-semibold text-slate-600">Reasoning</label>
            <select value={reasoning} onChange={(event) => setReasoning(event.target.value)} className="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm">
              <option value="none">关闭（默认）</option>
              <option value="low">低</option>
              <option value="medium">中</option>
              <option value="high">高</option>
            </select>
          </div>
        )}

        {message && <p className="mt-4 rounded-lg bg-rose-50 p-3 text-sm text-rose-700">{message}</p>}
        {status?.session_override && <p className="mt-4 text-xs text-amber-700">当前进程由启动参数锁定，需重启并移除覆盖参数后才能在 UI 切换。</p>}

        <div className="mt-6 flex justify-end gap-3">
          {mode === "reconfigure" && <button onClick={onComplete} className="rounded-lg border border-slate-200 px-4 py-2 text-sm">取消</button>}
          <button disabled={busy} onClick={refreshModelList} className="rounded-lg border border-slate-200 px-4 py-2 text-sm disabled:cursor-not-allowed disabled:text-slate-300">
            刷新模型
          </button>
          <button disabled={busy || !model} onClick={testOnly} className="rounded-lg border border-blue-200 px-4 py-2 text-sm text-blue-800 disabled:cursor-not-allowed disabled:text-slate-300">
            测试连接
          </button>
          <button disabled={busy || !model || status?.switch_allowed === false} onClick={save} className="rounded-lg bg-blue-800 px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">
            {busy ? "处理中…" : "保存切换"}
          </button>
        </div>
      </div>
    </div>
  );
}
