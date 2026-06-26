import { useState, useEffect } from "react";
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

  // On mount, check current status (setup mode only)
  useEffect(() => {
    if (mode === "reconfigure") return;
    (async () => {
      try {
        const status = await getConfigStatus();
        setConfigStatus(status);
        if (status.configured) {
          // Already configured, just proceed
          onComplete();
        } else {
          setStep("input");
        }
      } catch {
        // If server not reachable, still show setup
        setStep("input");
      }
    })();
  }, [mode, onComplete]);

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
        // Pre-select current model if known
        setStep("select");
      } else {
        setErrorMsg("未能获取模型列表，请确认 API Key 仍有效");
        setStep("error");
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
      // Call setup with a dummy model first to get available models
      // We'll use a different approach - hit status to validate the key
      const res = await fetch("/api/config/setup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey, model: "__test__" }),
      });
      if (!res.ok) {
        const data = await res.json();
        // If the error mentions model not in list, that's actually good - connection worked
        if (data.detail && data.detail.includes("不在可用列表中")) {
          // Prefer available_models from response body (new format)
          if (Array.isArray(data.available_models) && data.available_models.length > 0) {
            setModels(data.available_models);
          } else {
            // Fallback: extract from error message (legacy format)
            const match = data.detail.match(/可用模型: (.+)$/);
            if (match) {
              setModels(match[1].split(", ").filter(Boolean));
            }
          }
          setStep("select");
          return;
        }
        setErrorMsg(data.detail || "连接失败");
        setStep("error");
        return;
      }
      // If it succeeded somehow, we have the data
      const data = await res.json();
      // This shouldn't happen with __test__ model, but just in case
      setStep("select");
    } catch (e: any) {
      setErrorMsg(e.message || "网络错误");
      setStep("error");
    }
  };

  const handleSave = async () => {
    if (!selectedModel) return;
    setStep("testing");
    try {
      if (mode === "reconfigure") {
        await updateModel(selectedModel);
      } else {
        await setupConfig(apiKey, selectedModel);
      }
      setStep("done");
      // Wait a moment then proceed
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
        background: "#1a1a2e", borderRadius: 16, padding: 40, maxWidth: 520, width: "90%",
        boxShadow: "0 20px 60px rgba(0,0,0,0.5)", border: "1px solid #2a2a4a",
      }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 8 }}>
          <span style={{ fontSize: 28 }}>⚙️</span>
          <h2 style={{ margin: 0, color: "#e0e0ff", fontSize: 22, fontWeight: 700 }}>
            {mode === "reconfigure" ? "修改决策模型" : "TensileAgent 配置"}
          </h2>
        </div>
        {mode === "setup" && (
          <p style={{ color: "#8888aa", margin: "0 0 28px 0", fontSize: 14, lineHeight: 1.5 }}>
            首次使用需要配置远程决策模型的 API Key。
            你的 Key 只会保存在本地 <code style={{ color: "#aaccff" }}>agent/.env</code> 文件中。
          </p>
        )}
        {mode === "reconfigure" && (
          <p style={{ color: "#8888aa", margin: "0 0 28px 0", fontSize: 14, lineHeight: 1.5 }}>
            从百炼平台获取可用模型列表，选择新的决策模型。
          </p>
        )}

        {/* Step: Connection Check */}
        {step === "check" && (
          <div style={{ textAlign: "center", padding: 20 }}>
            <p style={{ color: "#8888aa" }}>正在检查配置状态...</p>
          </div>
        )}

        {/* Step: API Key Input */}
        {step === "input" && (
          <>
            <label style={{ color: "#aabbdd", fontSize: 13, fontWeight: 600, display: "block", marginBottom: 8 }}>
              百炼 API Key
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="sk-..."
              style={{
                width: "100%", padding: "12px 16px", borderRadius: 8, border: "1px solid #333",
                background: "#0f0f23", color: "#e0e0ff", fontSize: 15, outline: "none",
                boxSizing: "border-box",
              }}
              autoFocus
            />
            <p style={{ color: "#666688", fontSize: 12, marginTop: 6 }}>
              从 <a href="https://bailian.console.aliyun.com" target="_blank" style={{ color: "#6688cc" }}>百炼控制台</a> 获取
            </p>
            <button
              onClick={handleTestConnection}
              disabled={!apiKey.trim()}
              style={{
                width: "100%", marginTop: 20, padding: "12px 0", borderRadius: 8,
                border: "none", background: apiKey.trim() ? "#4a6cf7" : "#2a2a4a",
                color: apiKey.trim() ? "#fff" : "#666", fontSize: 15, fontWeight: 600,
                cursor: apiKey.trim() ? "pointer" : "not-allowed",
              }}
            >
              测试连接
            </button>
          </>
        )}

        {/* Step: Testing */}
        {step === "testing" && (
          <div style={{ textAlign: "center", padding: 20 }}>
            <p style={{ color: "#8888aa" }}>正在连接百炼服务...</p>
          </div>
        )}

        {/* Step: Select Model */}
        {step === "select" && (
          <>
            <p style={{ color: "#66cc88", fontSize: 14, marginBottom: 16 }}>
              ✅ 连接成功！请选择要使用的模型：
            </p>
            <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 300, overflowY: "auto" }}>
              {models.map((m) => (
                <label
                  key={m}
                  style={{
                    display: "flex", alignItems: "center", gap: 10, padding: "10px 14px",
                    borderRadius: 8, background: selectedModel === m ? "#2a3a6a" : "#0f0f23",
                    border: selectedModel === m ? "1px solid #4a6cf7" : "1px solid #2a2a4a",
                    cursor: "pointer", color: "#c0c0e0", fontSize: 14, transition: "all 0.15s",
                  }}
                >
                  <input
                    type="radio"
                    name="model"
                    value={m}
                    checked={selectedModel === m}
                    onChange={() => setSelectedModel(m)}
                    style={{ accentColor: "#4a6cf7" }}
                  />
                  <code style={{ fontSize: 13 }}>{m}</code>
                </label>
              ))}
            </div>
            <button
              onClick={handleSave}
              disabled={!selectedModel}
              style={{
                width: "100%", marginTop: 20, padding: "12px 0", borderRadius: 8,
                border: "none", background: selectedModel ? "#4a6cf7" : "#2a2a4a",
                color: selectedModel ? "#fff" : "#666", fontSize: 15, fontWeight: 600,
                cursor: selectedModel ? "pointer" : "not-allowed",
              }}
            >
              保存配置
            </button>
          </>
        )}

        {/* Step: Error */}
        {step === "error" && (
          <>
            <div style={{ background: "#2a1a1a", borderRadius: 8, padding: 16, marginBottom: 16 }}>
              <p style={{ color: "#ff6666", margin: 0, fontSize: 14 }}>❌ {errorMsg}</p>
            </div>
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
                width: "100%", padding: "12px 0", borderRadius: 8,
                border: "1px solid #4a6cf7", background: "transparent",
                color: "#4a6cf7", fontSize: 15, fontWeight: 600, cursor: "pointer",
              }}
            >
              重试
            </button>
          </>
        )}

        {/* Step: Done */}
        {step === "done" && (
          <div style={{ textAlign: "center", padding: 20 }}>
            <p style={{ color: "#66cc88", fontSize: 18, fontWeight: 600 }}>
              ✅ 配置完成！
            </p>
            <p style={{ color: "#8888aa", fontSize: 14, marginTop: 8 }}>
              正在进入主界面...
            </p>
          </div>
        )}

        {/* Footer */}
        <p style={{ color: "#555577", fontSize: 11, textAlign: "center", marginTop: 24, marginBottom: 0 }}>
          API Key 保存在 <code>agent/.env</code> · 不会被提交到 Git
        </p>
      </div>
    </div>
  );
}
