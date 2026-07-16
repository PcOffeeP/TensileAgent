# 本地决策模型接入实施方案

> 状态：已批准
> 版本：1
> 项目计划：docs/PROJECT_PLAN.md
> 项目计划版本：13.0

## 步骤目标与范围

将 Meta-Agent 默认决策后端改为本机 Ollama Qwen3.5-9B，保留 Qwen3-8B 本地对照和 qwen3.7-max 手动远程入口，并提供任务级模型快照、Web 切换和脱敏传输审计。本步骤不修改 MiniCPM 四字段视觉协议、模型训练、confidence 校准或正式 test。

## 实施方案

Ollama 由用户手动运行，不注册系统常驻服务。受 Git 跟踪的配置只保存默认值，Web 持久选择写入忽略的 `agent/config.local.yaml`，启动参数只覆盖当前进程。本地失败直接返回稳定错误，不自动切换远程。每个任务在创建时固定后端、模型、digest 和 reasoning 设置；逐轮决策请求与响应脱敏后写入 runtime trace，并在 Web 中回放。

## 执行清单

- [x] 安装 Ollama，提供 Qwen3.5-9B 与 Qwen3-8B 的 16K Modelfile。
- [x] 实现默认、本机持久和进程覆盖三级配置及任务级模型快照。
- [x] 实现本地模型发现、健康检查、切换锁和 fail-closed。
- [x] 实现本地/远程统一传输审计及 Web 回放、导出。
- [x] 更新 Web 配置界面、启动参数和运行说明。
- [x] 完成两个真实本地模型的 Agent-only A/B 和跨仓真实视频 smoke；详见 `docs/LOCAL_MODEL_ACCEPTANCE.md`。

## 预期结果

TensileAgent 默认不向第三方发送决策上下文；操作者可在 CLI 或 Web 显式选择本地/远程模型，并能查看每轮实际传输内容。任何模型切换都不修改受 Git 跟踪的运行配置，任何在途任务都不会因切换而改变后端。

## 验收标准

配置、故障门、模型快照、传输脱敏和 Web API 单元测试通过；前端构建和完整 Agent 测试通过；两个本地模型均完成原生 tool-call smoke；真实跨仓 smoke 即使因 MiniCPM 输出不完整失败，也必须保留本地决策模型和四字段拒绝证据。

## 风险与待确认事项

- [非阻塞] MiniCPM 当前可能只返回部分四字段；本步骤不得在 Agent 侧补造字段。
- [非阻塞] Qwen3.5-9B 若在固定 A/B 中低于 Qwen3-8B，则把本地默认调整为后者并保留对比报告。
- [已验证] 两个本地模型的功能验收指标相同且均达标，保留 Qwen3.5-9B 为默认；Qwen3-8B 延迟更低。
- [待优化] 真实 smoke 发现 MiniCPM 非法字段值和训练机代理 HTTP 502；Agent 已正确 fail closed。
