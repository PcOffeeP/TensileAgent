<!-- explain-project
verified_commit: 066dd5a77a6f6f344ac107453702dafabb4b371e
verified_worktree: clean
-->

# TensileAgent 项目导览

本文件是面向开发者的项目整体介绍，只记录当前实现；开发者期望与未来变更见 [`docs/PROJECT_TODO.md`](./PROJECT_TODO.md)。

## 一句话介绍

TensileAgent 是材料拉伸断裂视频分析系统：接收用户的一段自然语言问题和一段/多段视频，通过 HTTP 调用外部 MiniCPM-V 4.5 视觉推理服务，迭代定位断裂事件，最终输出版本化的结论（`fracture` / `no_fracture` / `unrecognized`）并按用户需求投影为可读回答。

## 核心链路

```text
用户输入 → Runner 初始化 → 迭代决策循环 → 视频采样与视觉推理 → 状态/边界更新 → 终止校验 → 结果投影
```

理解全文必须遵守的三条规则：

1. **决策模型只提建议，程序拥有最终控制权。** 状态转移、候选区间更新、冲突处理、终止条件均由 `IterativeAgent` 代码强制执行，LLM 只通过 Function Calling 输出 `sample_and_infer` 或 `terminate` 建议。
2. **V4.1 视觉契约只输出方向语义，不输出时间索引。** 视觉模型返回四字段 `{clip_state, fracture_mechanism, fracture_site, special_case}`；`clip_state` 仅给出搜索方向（向后 / 向前 / 当前区间内 / 无法判断），真正的事件边界由程序单调收缩。
3. **服务端预处理元数据是强制性证据。** 每轮视觉调用必须返回合规的 `preprocessing`（帧表 + deployment manifest）；缺失、漂移或非法即视为基础设施错误，不能作为有效语义结果进入状态机。

## 链路节点摘要

| 节点 | 职责 | 接收 | 产出 | 去向 |
|---|---|---|---|---|
| 1. 用户输入 | 解析用户意图与拒绝注入 | 视频路径 + 自然语言问题 | `UserIntent`（请求字段、是否需证据、语言等） | Runner |
| 2. Runner 初始化 | 按 stage 装配依赖、冻结后端/模型/视觉契约、生成初始化失败信封 | 配置、视频元数据、用户意图 | 装配完成的依赖与冻结的运行时身份，或按 stage 返回初始化失败信封 | `IterativeAgent` |
| 3. 迭代决策循环 | 维护状态机，调用决策模型选择动作 | 当前状态、候选区间、历史证据 | Function Call（`sample_and_infer` / `terminate`） | 采样/终止校验 |
| 4. 视频采样与视觉推理 | 裁剪临时 MP4、编码为 Base64 data URL、调用 MiniCPM-V | `sample_range`、`task_mode` | 解析后的四字段输出 + diagnostics | 状态/边界更新 |
| 5. 状态与事件边界更新 | 根据 clip_state 或 V2 输出更新候选区间、覆盖计数、冲突计数 | 单轮模型输出 | 新状态、`V41EventBounds`、冲突记录 | 下一轮决策或终止 |
| 6. 终止校验 | 验证证据数量、事件边界收敛、覆盖完成度 | `terminate` 参数 | 通过 / 拒绝 + 原因 | 最终结果聚合或继续迭代 |
| 7. 结果投影 | 把公共结论映射为用户请求字段，生成可读回答 | `FinalOutput` + `UserIntent` | 用户可见的回答与字段可用性说明 | 外部调用方 |

## 关键细节

### Runner 初始化

- **装配顺序**：意图解析（`agent/runner.py:145`）→ 配置加载（`:157`）→ `_runtime` 元数据（`:195`）→ 视频元数据（`:207`，先 `ffprobe`、失败后 `cv2` 回退）→ LLM 后端（`:210` → `agent/llm.py:281`）→ 推理客户端（`:212` → `agent/inference.py:684`）+ 预检（`:213` → `agent/inference.py:472`）→ `ClipBuilder`（`:216`）→ `IterativeAgent`（`:220-229`）。
- **失败信封**：任一 stage 失败即停止，返回带 stage 标签的失败信封，顺序为 `configuration` → `input` → `decision_backend` → `inference_transport` → `sampling` → `internal`。
- **产物语义**：装配成功后，运行时身份（`agent_config_snapshot`、local 模型 digest、`deployment_snapshot`）和依赖实例在后续迭代中保持冻结。

代码入口：
- `agent/runner.py` — `run_one`
- `agent/llm.py` — `AgentLLMFactory`
- `agent/inference.py` — `LlamaFactoryInferenceClient.__init__` / `preflight`

### V4.1 方向语义与单调事件边界

- **选择**：V4.1 不再接受模型输出的 `fracture_between` 或绝对时间，改用四字段中的 `clip_state` 作为方向信号。
- **原因**：避免模型直接预测时间索引带来的幻觉；把定位收敛交给程序维护的单调可信区间。
- **收益**：`V41EventBounds` 只收缩不扩张，冲突被记录并拒绝，保证事件区间的可信度。
- **代价**：需要更多轮次和至少两次一致正证据才能终止；`临界未断裂` 等中间态只能作为 prospective 线索，必须经后续 `发生断裂`/`已断裂` 确认。

代码入口：
- `agent/v4_1_evidence.py` — `V41EventBounds.apply`
- `agent/iterative_agent.py` — `_transition_v4_1`

测试依据：
- `tests/test_v4_1_runtime_contract.py`
- `tests/test_v4_1_contract_artifact.py`

### 覆盖检查与无断裂判定

- **选择**：全局第一次阴性结果不会直接判定 `no_fracture`，而是进入程序强制的 5 个固定重叠窗口覆盖检查。
- **原因**：单轮全视频采样最多 8 帧，无法证明全视频无断裂；5 个窗口覆盖全时长，可降低漏检。
- **收益**：`no_fracture` 结论有结构性证据支撑。
- **代价**：无断裂视频需要更多轮次（最多 1 次全局 + 5 次覆盖）。

代码入口：
- `agent/iterative_agent.py` — `_coverage_ranges`、`_has_complete_no_fracture_coverage`、`_transition` 中 `COVERAGE` 分支

### 终止规则与证据门槛

- `fracture`：至少 2 轮独立断裂证据，其中至少 1 轮来自严格局部 clip；V4.1 还要求 `event_bounds.publishable(tolerance)`。
- `no_fracture`：5 个覆盖窗口全部得到合法阴性。
- `unrecognized`：10 轮耗尽、连续基础设施失败、不可解决冲突、非法输出、未夹紧/视频异常/无法判断经复查一致等。
- **选择**：由代码而非模型决定何时可以终止，模型 `terminate` 仅作为提议。
- **原因**：防止模型过早或过晚下结论，保证输出 schema 与证据一致。

代码入口：
- `agent/iterative_agent.py` — `_can_terminate`、`_force_terminate`、`_build_fracture_args`

### 视觉 Prompt 与契约隔离

- **选择**：视觉 Prompt 完全来自冻结契约 `agent/contracts/tensile_vlm_v4_1.json`；`IterativeAgent` 仍构造并传递 `prompt` 参数，但 `LlamaFactoryInferenceClient.infer` 立即丢弃它，改用契约中的 `analysis.system_prompt` / `analysis.user_prompt`。
- **原因**：确保用户原话、决策模型历史、提示注入都不会进入视觉模型请求。
- **现状缺口**：上游仍保留冗余 `prompt` 构造与导出，属于 TODO 已记录的清理项（见 `docs/PROJECT_TODO.md` “简化视觉 Prompt 传输链路”）。

代码入口：
- `agent/inference.py` — `LlamaFactoryInferenceClient.infer`
- `agent/schema.py` — `ToolSampleAndInfer._discard_legacy_prompt`
- `agent/contract.py` — `load_visual_contract`

## 跨切机制

### 配置与契约版本

- **配置合并**：默认路径下，`_SESSION_OVERRIDES` > `config.local.yaml` > `config.yaml` 逐层 `deep-merge`；自定义 `--config <path>` 为裸读，不参与 local 合并。
- **契约版本**：优先级为 `config` > 环境变量 `INFERENCE_CONTRACT_VERSION` > 默认 `V2`；**不允许运行时自动从 V4.1 降级到 V2**。
- **Mock 模式**：`INFERENCE_MOCK=1` 在进程级启用 `MockInferenceClient`，无需真实视觉服务即可验证链路。
- **请求大小限制**：`max_request_size` 默认 `32 MiB`，必须为大于 0 的整数。
- **预检契约**：`LlamaFactoryInferenceClient` 初始化期发起 `GET /tensile/contract`，校验 version、hash、capabilities、deployment_manifest；失败视为推理传输层错误。
- 视觉契约 JSON 通过 SHA256 校验；任务预检时冻结 deployment manifest，漂移则拒绝。

代码入口：
- `agent/config.yaml`
- `agent/config_util.py` — 配置加载与合并
- `agent/contract.py`
- `agent/run.py` — CLI 参数解析
- `agent/inference.py` — `LlamaFactoryInferenceClient.preflight`

### LLM 后端与身份冻结

- **三种决策后端**：
  - `remote`：必须提供 `model`、`base_url`、`api_key`，缺一即初始化失败。
  - `local`：eager 探测 Ollama；离线、模型缺失或 digest 不符均 fail-closed。
  - `deterministic`：仅用于验收/测试，按固定规则返回动作。
- **身份冻结三机制**：
  1. Web API 创建任务时捕获 `agent_config_snapshot`，后续运行以该快照为决策配置来源。
  2. Preflight 的 `deployment_snapshot` 在运行期校验 deployment drift，漂移即拒绝。
  3. Local 模型加载后固化其 digest，作为模型权重身份校验依据。

代码入口：
- `agent/llm.py` — `AgentLLMFactory`
- `agent/runner.py` — `run_one` 中 snapshot 校验与装配顺序

### 错误隔离

- **基础设施错误**（采样失败、HTTP 失败、deployment drift、预处理元数据缺失）：记录但不驱动状态转移；连续 2 次强制终止，返回 `RunnerResult(ok=False)`。
- **验证错误**（非法模型输出）：记录低置信；连续 2 次触发候选区间扩展。
- **冲突**：V4.1 中冲突更新被 `V41EventBounds` 拒绝；不可解决冲突 3 次以上强制 `unrecognized`。

代码入口：
- `agent/iterative_agent.py` — `_transition`、`_force_terminate`
- `agent/inference.py` — `_validate_preprocessing_meta`

### 可追溯与脱敏

- 每轮保存 `SampleAndInferDiagnostics`（request_id、帧表、clip hash、deployment manifest、耗时等）。
- LLM 传输记录保存到 `data/08_runtime/llm_traces/<task-id>/`，已脱敏（不含 API Key、Base64、绝对路径）。
- 最终 `visual_evidence` 提供引用指针（round、sample_range、frame_timestamps、clip_hash、request_id），但标注为 `experimental`。

代码入口：
- `agent/llm_trace.py`
- `agent/iterative_agent.py` — `_build_round_diagnostics`、`_build_visual_evidence`

## 其他重要特性

### Web 工作台

- FastAPI 后端 + React/Vite 前端，提供文件上传、任务队列、SSE 实时事件流、历史与模型传输回放。
- 与 CLI 共享同一个 `run_one` 执行内核。

代码入口：
- `agent/web_api.py`
- `web/src/App.tsx`

### 批量验收与评分

- `scripts/run_v4_1_acceptance_batch.py` + `scripts/score_v4_1_acceptance.py` 用于冻结 V4.1 批量验收与 Stage G 评分。
- V2 对比通过显式 `config.v2.comparison.yaml` 运行，不会自动降级。

代码入口：
- `agent/acceptance_batch.py`
- `agent/scoring_v4_1.py`

### Mock 模式

- `INFERENCE_MOCK=1` 或 `--mock` 使用 `MockInferenceClient`，无需真实视觉服务即可验证链路。

代码入口：
- `agent/inference.py` — `MockInferenceClient`
- `agent/http_vlm_stub.py` — 本地协议 Stub

## 当前限制与未知

- **默认值不一致**：决策模型 `temperature` 的代码兜底默认值为 `0.7`，而 `config.yaml` 中默认写为 `0.2`；两者当前独立生效。
- **local 回退 remote**：`config.yaml` 将决策后端默认写为 `local`，但当 Ollama 本地配置缺失/探测失败时，代码会兜底使用 `remote`。
- 当前交付为 `tensile-vlm/v4.1` 中间模型集成，README 明确说明**不能宣称为 final / full-data / production-passed**；Stage G 全量 110 条性能是中间结果，历史质量门仍失败。
- 决策模型与视觉模型质量仍在独立优化；本仓库只负责 Agent 端。
- `confidence` 数值保持 `null`，`evidence_level` 是确定性分类；校准版本尚未接入。
- `visual_evidence` 标记为 `experimental`，可靠性未经验证。
- 用户意图识别当前为纯正则匹配，未调用决策模型；该差异已记录在 `docs/PROJECT_TODO.md`。
- 工作区当前为 clean 状态（见顶部 `verified_worktree`）；历史 `.pi/` 下文件删除已清理，不再影响项目源码。
- `agent/langgraph_agent/` 为未跟踪目录，当前指南未纳入核心链路说明。
