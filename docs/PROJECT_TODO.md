# Project TODO

记录项目开发者的期望与当前实现之间尚未解决的差异。

## 待处理

### 意图识别模型调用超时与性能

- **关联主题**：用户输入 → `parse_user_intent`（`agent/interaction.py:336-340`）→ `chat_with_tools` → LLM/工具后端
- **开发者期望**：意图识别模型调用应具备可控的超时机制，避免后端 hang 住时长时间阻塞主链路；调用开销应尽量小，不应在每次请求中重复执行不必要的初始化与健康检查。
- **当前实现**：`agent/interaction.py:336-340` 调用 `chat_with_tools` 时未传入 `timeout` 参数，端点 hang 住可能导致调用长时间阻塞。同时每次调用都会重复执行 `load_config` 以及 local 后端（Ollama）健康检查，实测增加约 3 秒开销。
- **存在差异**：当前实现无超时保护且存在重复初始化/健康检查导致的性能损耗，不符合“可控、低延迟”的预期。
- **代码依据**：
  - `agent/interaction.py:336-340` `chat_with_tools` 调用无 `timeout`
  - `agent/interaction.py` 每次调用重复 `load_config` 与 local 后端健康检查
- **待决定或后续动作**：本次改造明确将超时机制列为开放问题，暂不实现。后续需立项跟踪：引入有限 timeout（如配置化 `intent_timeout_seconds`），并考虑缓存/复用配置加载与健康检查结果，避免每次意图识别调用重复开销。
- **记录版本**：本次改造完成时的描述性状态（工作区存在未提交变更）

### 决策模型（心智模型）Prompt

- **关联主题**：TensileAgent 决策层 → LLM 后端 → Prompt 契约（`agent/prompts.py`）→ 迭代状态机
- **开发者期望**：完成 Prompt 设计，并通过典型场景、异常路径和回归用例验证其稳定性与效果。
- **当前实现**：已存在 V2/V4.1 两个系统 Prompt（`TENSILE_AGENT_SYSTEM_PROMPT`、`TENSILE_AGENT_V4_1_SYSTEM_PROMPT`）和每轮用户上下文构建函数 `build_tensile_agent_user_context`；`agent/iterative_agent.py` 按契约版本选择系统 Prompt 并拼接用户上下文后调用 LLM。`tests/test_prompts_tensile.py` 校验了 Prompt 关键字段和用户上下文内容；`scripts/run_local_model_ab.py` 用于本地模型 A/B 对比，但不是针对 Prompt 稳定性/异常路径的回归验证。
- **存在差异**：Prompt 模板已具备并投入运行，但仓库中没有针对“典型场景、异常路径和回归用例”的系统化 Prompt 稳定性与效果验证。
- **代码依据**：
  - `agent/prompts.py:47-225` Prompt 定义与构建函数
  - `agent/iterative_agent.py:509-525` 系统 Prompt 选择与上下文构建
  - `tests/test_prompts_tensile.py` 基础断言
  - `scripts/run_local_model_ab.py` A/B 脚本（非回归测试）
- **待决定或后续动作**：补充典型场景、异常路径和回归用例的验证机制，明确完成标准。
- **记录版本**：`c2144117`（工作区存在未提交变更）

### 核心功能主链路失败兜底逻辑核查

- **关联主题**：核心功能主链路 → 外部工具调用、视频读取、模型推理、LLM 调用、文件 I/O 等关键步骤的错误处理与 fallback 策略
- **开发者期望**：核心功能主链路的关键步骤（如外部工具调用、视频读取、模型推理、LLM 调用、文件 I/O 等）在可能失败时具有明确的失败兜底逻辑，而不是直接崩溃或静默失败。
- **当前实现**：仅在 runner 初始化视频源元数据时确认存在 FFprobe 失败回退 CV2 的兜底逻辑：`build_video_meta()` 先尝试 ffprobe，ffprobe 不可用或抛错时回退到 cv2，cv2 也失败时抛出 `RuntimeError` 并附带诊断信息；相关测试覆盖 ffprobe 成功、ffprobe 失败回退 cv2、两者均失败三种路径。项目其余核心链路步骤的兜底情况尚未系统核查。
- **存在差异**：runner 视频元数据装配的兜底机制已确认，但其他核心主链路步骤是否均具备类似 fallback 或明确的错误处理策略尚不明确，可能存在缺少兜底导致直接崩溃或静默失败的风险。
- **代码依据**：
  - `agent/runner.py:63-133` `build_video_meta()` 中 ffprobe 失败回退 cv2、cv2 失败抛出 `RuntimeError` 的兜底实现
  - `tests/test_runner.py:30-113` 视频元数据装配兜底路径的测试覆盖
- **待决定或后续动作**：逐段审查核心主链路（外部工具调用、视频解码/读取、模型/LLM 推理、文件 I/O、网络请求等），识别可能出错且缺少兜底的步骤，逐一补齐合理的 fallback 或明确的错误处理策略，并补充对应测试。
- **记录版本**：`2ba6151`（工作区存在未提交变更）

## 待确认

无。

## 已解决

### 用户需求识别

- **关联主题**：用户输入 → Runner 输入解析 → `parse_user_intent`（`agent/interaction.py`）→ 结果投影（`project_result`）
- **开发者期望**：设计并验证由决策模型识别用户需求，或采用“模型理解 + 确定性代码校验与兜底”的混合方案。
- **当前实现**：已在 `parse_user_intent` 内实现“决策模型识别为主 + 代码三层合规校验 + 现有正则兜底”的混合架构。`agent/prompts.py` 新增意图识别 Prompt 与 8 字段 JSON 输出契约；`agent/schema.py` 将 `UserIntent.rejection_code` 从 `str|None` 收敛为 `Literal[5 值]|None`；`agent/interaction.py` 在模型路径后依次执行安全复核、pydantic 合法性校验、一致性校验，除安全复核命中由代码直接裁决改写为 `action="unsupported"` 外，其余校验失败、模型异常、JSON 不可解析或 `backend=deterministic` 时均回退到现有正则实现，保证行为不劣化。
- **存在差异**：无。混合架构已落地，正则兜底保留。
- **代码依据**：
  - `agent/prompts.py` 意图识别 Prompt 与 JSON 输出契约
  - `agent/schema.py` `UserIntent.rejection_code` 5 值 `Literal` 约束
  - `agent/interaction.py` 模型调用路径、三层校验与正则兜底接线
  - `tests/test_interaction.py` 保留原有确定性正则用例
- **待决定或后续动作**：P5 已完成 TODO 状态更新；混合架构与新增模型路径的 mock 测试已补齐并实测全绿（排除 3 个 fastapi 缺失文件后 444 passed、0 failed；`backend=deterministic` 结果逐字节一致），无需再声明“不声明已全部通过”。
- **记录版本**：本次改造完成时的描述性状态（不再引用过期 commit hash；工作区存在未提交变更）

### 简化视觉 Prompt 传输链路

- **关联主题**：`sample_and_infer` 工具 → 视觉推理 HTTP 客户端 → 冻结视觉契约
- **开发者期望**：移除上游为 `sample_and_infer` 构造并传递、随后又被 HTTP 推理客户端丢弃的冗余 `prompt` 参数；由推理客户端直接根据冻结的视觉契约选择并发送固定、版本化的主分析 Prompt（以及按需的固定 Evidence Prompt），同步收紧接口、schema 与测试，确保用户原话和决策模型内容仍不会进入视觉模型请求。
- **当前实现**：已按用户确认的 Option A 彻底移除冗余 `prompt` 参数。`build_sample_and_infer_prompt` 已从 `agent/prompts.py` 删除，不再作为公共 API 导出（`agent/__init__.py` 导出同步清理）；`InferenceClient` Protocol、`LlamaFactoryInferenceClient` 与 `MockInferenceClient` 的 `infer` 签名由 `(video_input, prompt)` 收紧为 `(video_input)`，不再执行 `del prompt`，Mock 响应回调改为单参；`IterativeAgent._execute_sample_and_infer` 不再构造 prompt，删除 `max_prompt_length` 校验与 `prompt_too_long` 错误分支；`scripts/run_strategy_ab.py` 同步清理，包括移除 `_visual_round` 的死参数 `config`；测试已适配新签名，并删除 2 个失效用例。视觉请求文本的唯一来源仍为冻结契约 `self.analysis` / `self.evidence`；schema 层 `_discard_legacy_prompt` 防御保留；攻击测试验证旧双参调用会立即触发 `TypeError`，无静默失败。
- **存在差异**：无。冗余 prompt 参数已彻底移除，接口收紧完成，安全契约保持不变。
- **代码依据**：
  - `agent/prompts.py` 已移除 `build_sample_and_infer_prompt`
  - `agent/__init__.py` 已移除 `build_sample_and_infer_prompt` 公共导出
  - `agent/inference.py` `infer` 签名收紧为 `(video_input)`，不再包含 `prompt`
  - `agent/inference.py` `infer_evidence` 仍从 `self.evidence` 读取固定 Evidence Prompt
  - `agent/schema.py:163-178` `ToolSampleAndInfer` 保留 `_discard_legacy_prompt` 防御
  - `agent/iterative_agent.py` `_execute_sample_and_infer` 不再构造/传递 prompt
  - `scripts/run_strategy_ab.py` 同步清理冗余 prompt 与死参数 `config`
  - 相关测试已适配新签名并移除失效用例
- **待决定或后续动作**：已完成。无需后续动作。
- **记录版本**：`94174d5`（工作区存在未提交变更）
