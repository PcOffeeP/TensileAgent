# Project TODO

记录项目开发者的期望与当前实现之间尚未解决的差异。

## 待处理

### 用户需求识别

- **关联主题**：用户输入 → Runner 输入解析 → `parse_user_intent`（`agent/interaction.py`）→ 结果投影（`project_result`）
- **开发者期望**：设计并验证由决策模型识别用户需求，或采用“模型理解 + 确定性代码校验与兜底”的混合方案。
- **当前实现**：用户问题仅在 `agent/interaction.py:parse_user_intent` 中做确定性正则匹配；根据中文/英文关键词、拒绝/注入/矛盾模式等返回 `UserIntent`。`agent/runner.py:run_one` 直接调用该函数，未调用任何决策模型进行意图识别。测试覆盖见 `tests/test_interaction.py`。
- **存在差异**：开发者期望决策模型参与识别或采用混合方案，而当前实现为纯确定性代码，无模型理解环节。
- **代码依据**：
  - `agent/interaction.py:21-108` 纯正则解析
  - `agent/runner.py:174` 直接调用 `parse_user_intent(question)`
  - `tests/test_interaction.py` 覆盖确定性用例
- **待决定或后续动作**：是否引入决策模型进行意图识别，以及如何设计兜底校验规则。
- **记录版本**：`c2144117`（工作区存在未提交变更）

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

### 简化视觉 Prompt 传输链路

- **关联主题**：`sample_and_infer` 工具 → 视觉推理 HTTP 客户端 → 冻结视觉契约
- **开发者期望**：移除上游为 `sample_and_infer` 构造并传递、随后又被 HTTP 推理客户端丢弃的冗余 `prompt` 参数；由推理客户端直接根据冻结的视觉契约选择并发送固定、版本化的主分析 Prompt（以及按需的固定 Evidence Prompt），同步收紧接口、schema 与测试，确保用户原话和决策模型内容仍不会进入视觉模型请求。
- **当前实现**：
  - 视觉 Prompt 已完全由冻结契约提供：`LlamaFactoryInferenceClient.infer` 接受 `prompt` 参数后立即 `del prompt`，使用 `self.analysis["system_prompt"]` 和 `self.analysis["user_prompt"]`；`infer_evidence` 使用 `self.evidence["system_prompt"]` 和 `self.evidence["user_prompt"]`。
  - `ToolSampleAndInfer` schema 已移除 `prompt` 字段，并通过 `_discard_legacy_prompt` 丢弃旧调用中的遗留 `prompt`。
  - 测试验证用户/决策模型内容不会进入视觉请求：`test_tool_sample_and_infer_discards_legacy_prompt`、`test_tool_sample_and_infer_never_exposes_legacy_prompt`、`test_build_sample_and_infer_prompt_has_required_elements`。
  - 但 `IterativeAgent._execute_sample_and_infer` 仍调用 `build_sample_and_infer_prompt` 构造并传递 `prompt` 给 `inference_client.infer`，且进行 `max_prompt_length` 校验；`agent/__init__.py` 仍将 `build_sample_and_infer_prompt` 作为公共 API 导出。这部分属于仍需清理的冗余接口。
- **存在差异**：核心目标（契约化固定 Prompt、隔离用户/决策模型内容）已实现，但上游仍保留并传递被丢弃的冗余 `prompt` 参数，接口尚未完全收紧。
- **代码依据**：
  - `agent/inference.py:483-489` `infer` 方法 `del prompt` 并使用契约 Prompt
  - `agent/inference.py:703-708` `infer_evidence` 使用契约 Evidence Prompt
  - `agent/schema.py:163-178` `ToolSampleAndInfer` 丢弃遗留 `prompt`
  - `agent/iterative_agent.py:1672-1689` 仍构造并传递 `prompt`
  - `agent/__init__.py:12,60-61` 仍导出 `build_sample_and_infer_prompt`
  - `tests/test_schema.py:203-228`、`tests/test_prompts_tensile.py:92-104` 相关断言
- **待决定或后续动作**：是否从 `IterativeAgent._execute_sample_and_infer` 和 `InferenceClient.infer` 签名中移除 `prompt` 参数，并同步清理测试与 `agent/__init__.py` 导出。
- **记录版本**：`c2144117`（工作区存在未提交变更）

## 待确认

无。

## 已解决

无。
