import { useState, useEffect, useRef } from "react";
import { getConfigStatus, setupConfig, updateModel, ConfigStatus } from "../api";

interface SetupDialogProps {
  onComplete: () => void;
  mode?: "setup" | "reconfigure";
}

export default function SetupDialog({ onComplete, mode = "setup" }: SetupDialogProps) {
  const [step, setStep] = useState<"check" | "input" | "testing" | "select" | "done" | "error">(() =>
    mode === "reconfigure" ? "testing" : "check"
  );
  const [configStatus, setConfigStatus] = useState<ConfigStatus | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  // Keep a stable reference to the latest onComplete
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  // On mount, check current status (setup mode only)
  useEffect(() => {
    if (mode === "reconfigure") return;
    (async () => {
      try {
        const status = await getConfigStatus();
        setConfigStatus(status);
        if (status.configured) {
          // Already configured, just proceed
          onCompleteRef.current();
        } else {
          setStep("input");
        }
      } catch {
        // If server not reachable, still show setup
        setStep("input");
      }
    })();
  }, [mode]);

  // Reconfigure mode: fetch available models using saved API key
  useEffect(() => {
    if (mode !== "reconfigure") return;
    fetchAvailableModels();
  }, [mode]);

  async function fetchAvailableModels() {
    setStep("testing");
    setErrorMsg("");
    try {
      const data = await updateModel("");
      if (data.available_models && data.available_models.length > 0) {
        setModels(data.available_models);
        setStep("select");
      } else {
        // 列表为空 → 进入手动输入
        setModels([]);
        setStep("select");
      }
    } catch (err: any) {
      setErrorMsg(err.message || "获取模型列表失败");
      setStep("error");
    }
  }

  const handleTestConnection = async () => {
    if (!apiKey.trim()) return;
    setStep("testing");
    setErrorMsg("");
    try {
      const data = await setupConfig(apiKey, "", "test");
      if (data.available_models && data.available_models.length > 0) {
        setModels(data.available_models);
        setStep("select");
      } else {
        // 列表为空 → 进入手动输入
        setModels([]);
        setStep("select");
      }
    } catch (err: any) {
      setErrorMsg(err.message || "网络错误");
      setStep("error");
    }
  };

  const handleSave = async () => {
    if (!selectedModel.trim()) return;
    setStep("testing");
    setErrorMsg("");
    try {
      if (mode === "reconfigure") {
        await updateModel(selectedModel);
      } else {
        await setupConfig(apiKey, selectedModel, "setup");
      }
      setStep("done");
      setTimeout(() => onComplete(), 1500);
    } catch (e: any) {
      setErrorMsg(e.message || "保存失败");
      setStep("error");
    }
  };

  // ── Render ──

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 9999,
      display: "flex", alignItems: "center", justifyContent: "center",
      background: "rgba(0,0,0,0.6)", backdropFilter: "blur(4px)",
    }}>
      <div style={{
        background: "#FFFFFF", borderRadius: 16, padding: 40, maxWidth: 520, width: "90%",
        boxShadow: "0 20px 60px rgba(0,47,167,0.15)", border: "1px solid #e2e8f0",
      }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <span style={{ fontSize: 28 }}>⚙️</span>
          <h2 style={{ margin: 0, color: "#0f172a", fontSize: 22, fontWeight: 700 }}>
            {mode === "reconfigure" ? "修改决策模型" : "TensileAgent 配置"}
          </h2>
        </div>
        {mode === "setup" && (
          <p style={{ color: "#64748b", margin: "0 0 28px 0", fontSize: 14, lineHeight: 1.5 }}>
            首次使用需要配置远程决策模型的 API Key。
            你的 Key 只会保存在本地 <code style={{ color: "#002FA7", background: "#f1f5f9", padding: "2px 6px", borderRadius: 4 }}>agent/.env</code> 文件中。
          </p>
        )}
        {mode === "reconfigure" && (
          <p style={{ color: "#64748b", margin: "0 0 28px 0", fontSize: 14, lineHeight: 1.5 }}>
            从百炼平台获取可用模型列表，选择新的决策模型。
          </p>
        )}

        {/* Step: Connection Check */}
        {step === "check" && (
          <div style={{ textAlign: "center", padding: 20 }}>
            <p style={{ color: "#64748b" }}>正在检查配置状态...</p>
          </div>
        )}

        {/* Step: API Key Input */}
        {step === "input" && (
          <>
            <label style={{ color: "#334155", fontSize: 13, fontWeight: 600, display: "block", marginBottom: 8 }}>
              百炼 API Key
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              style={{
                width: "100%", padding: "12px 16px", borderRadius: 8, border: "1px solid #cbd5e1",
                background: "#f8fafc", color: "#0f172a", fontSize: 15, outline: "none",
                boxSizing: "border-box",
                transition: "border-color 0.2s"
              }}
              autoFocus
            />
            <p style={{ color: "#64748b", fontSize: 12, marginTop: 6 }}>
              从 <a href="https://bailian.console.aliyun.com" target="_blank" style={{ color: "#002FA7", textDecoration: "none" }}>百炼控制台</a> 获取
            </p>
            <button
              onClick={handleTestConnection}
              disabled={!apiKey.trim()}
              style={{
                width: "100%", marginTop: 20, padding: "12px 0", borderRadius: 8,
                border: "none", background: apiKey.trim() ? "#002FA7" : "#e2e8f0",
                color: apiKey.trim() ? "#fff" : "#94a3b8", fontSize: 15, fontWeight: 600,
                cursor: apiKey.trim() ? "pointer" : "not-allowed",
                transition: "background 0.2s"
              }}
            >
              测试连接
            </button>
          </>
        )}

        {/* Step: Testing */}
        {step === "testing" && (
          <div style={{ textAlign: "center", padding: 20 }}>
            <p style={{ color: "#64748b" }}>正在连接百炼服务...</p>
          </div>
        )}

        {/* Step: Select Model */}
        {step === "select" && (
          <>
            {models.length > 0 ? (
              <p style={{ color: "#10b981", fontSize: 14, marginBottom: 16 }}>
                ✅ 连接成功！请选择要使用的模型：
              </p>
            ) : (
              <p style={{ color: "#f59e0b", fontSize: 14, marginBottom: 16 }}>
                ⚠️ 未获取到推荐模型列表，请手动输入
              </p>
            )}

            {models.length > 0 && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 200, overflowY: "auto" }}>
                <p style={{ color: "#64748b", fontSize: 12, margin: 0 }}>推荐模型（从百炼平台获取）</p>
                {models.map((m) => (
                  <label
                    key={m}
                    style={{
                      display: "flex", alignItems: "center", gap: 10, padding: "10px 14px",
                      borderRadius: 8, 
                      background: selectedModel === m ? "rgba(0,47,167,0.05)" : "#f8fafc",
                      border: selectedModel === m ? "1px solid #002FA7" : "1px solid #e2e8f0",
                      cursor: "pointer", 
                      color: selectedModel === m ? "#002FA7" : "#334155", 
                      fontSize: 14, transition: "all 0.15s",
                      fontWeight: selectedModel === m ? 600 : 400
                    }}
                  >
                    <input
                      type="radio"
                      name="model"
                      value={m}
                      checked={selectedModel === m}
                      onChange={() => setSelectedModel(m)}
                      style={{ accentColor: "#002FA7" }}
                    />
                    <code style={{ fontSize: 13 }}>{m}</code>
                  </label>
                ))}
              </div>
            )}

            {/* 手动输入始终可见 */}
            <div style={{ marginTop: "1rem", borderTop: "1px solid #e2e8f0", paddingTop: "1rem" }}>
              <p style={{ color: "#475569", fontSize: 13, marginBottom: 8, fontWeight: 500 }}>
                {models.length > 0 ? "或手动输入模型名" : "请输入模型名"}
              </p>
              <input
                type="text"
                placeholder="例如 qwen-max, qwen-plus"
                value={models.includes(selectedModel) ? "" : selectedModel}
                onChange={(e) => setSelectedModel(e.target.value)}
                style={{
                  width: "100%", padding: "12px 16px", borderRadius: 8, border: "1px solid #cbd5e1",
                  background: "#f8fafc", color: "#0f172a", fontSize: 15, outline: "none",
                  boxSizing: "border-box",
                  transition: "border-color 0.2s"
                }}
              />
            </div>

            <button
              onClick={handleSave}
              disabled={!selectedModel.trim()}
              style={{
                width: "100%", marginTop: 20, padding: "12px 0", borderRadius: 8,
                border: "none", background: selectedModel.trim() ? "#002FA7" : "#e2e8f0",
                color: selectedModel.trim() ? "#fff" : "#94a3b8", fontSize: 15, fontWeight: 600,
                cursor: selectedModel.trim() ? "pointer" : "not-allowed",
                transition: "background 0.2s"
              }}
            >
              保存配置
            </button>
          </>
        )}

        {/* Step: Error */}
        {step === "error" && (
          <>
            <div style={{ background: "#fef2f2", borderRadius: 8, padding: 16, marginBottom: 16, border: "1px solid #fee2e2" }}>
              <p style={{ color: "#ef4444", margin: 0, fontSize: 14 }}>❌ {errorMsg}</p>
            </div>
            <div style={{ display: "flex", gap: 12 }}>
              <button
                onClick={() => {
                  setErrorMsg("");
                  if (mode === "reconfigure") {
                    fetchAvailableModels();
                  } else {
                    setStep("input");
                  }
                }}
                style={{
                  flex: 1, padding: "12px 0", borderRadius: 8,
                  border: "1px solid #002FA7", background: "transparent",
                  color: "#002FA7", fontSize: 15, fontWeight: 600, cursor: "pointer",
                }}
              >
                重试
              </button>
              <button
                onClick={() => {
                  setErrorMsg("");
                  setModels([]);
                  setStep("select");
                }}
                style={{
                  flex: 1, padding: "12px 0", borderRadius: 8,
                  border: "1px solid #cbd5e1", background: "transparent",
                  color: "#64748b", fontSize: 15, fontWeight: 600, cursor: "pointer",
                }}
              >
                跳过，手动输入
              </button>
            </div>
          </>
        )}

        {/* Step: Done */}
        {step === "done" && (
          <div style={{ textAlign: "center", padding: 20 }}>
            <p style={{ color: "#10b981", fontSize: 18, fontWeight: 600 }}>
              ✅ 配置完成！
            </p>
            <p style={{ color: "#64748b", fontSize: 14, marginTop: 8 }}>
              正在进入主界面...
            </p>
          </div>
        )}

        {/* Footer */}
        <p style={{ color: "#94a3b8", fontSize: 11, textAlign: "center", marginTop: 24, marginBottom: 0 }}>
          API Key 保存在 <code style={{ background: "#f1f5f9", padding: "2px 4px", borderRadius: 4 }}>agent/.env</code> · 不会被提交到 Git
        </p>
      </div>
    </div>
  );
}
