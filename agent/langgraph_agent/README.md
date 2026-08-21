# LangGraph 实验分支说明

## 1. 实验目标

在 `experiment/langgraph-agent` 分支中，建立与当前 `IterativeAgent` **并行** 的 LangGraph 实验实现。通过逐步映射现有确定性状态机到 LangGraph 的 StateGraph，验证标准化 Agent 架构在本项目中的可行性与行为一致性，**不立即替换主路径**。

## 2. 当前原则

- **分支隔离**：所有 LangGraph 相关探索仅限本分支。
- **目录并行**：实现代码放在 `agent/langgraph_agent/`，与现有 `agent/` 模块互不侵入。
- **默认仍使用 `IterativeAgent`**：CLI、Web API 等入口在第一阶段保持原默认路径不变。
- **小步验证**：每个阶段必须有 golden case 行为对比，确认等价后再进入下一阶段。

## 3. 非目标（第一阶段不做）

- 不替换 CLI/Web 的默认执行路径。
- 不扩大 LLM 自主权或改变调用策略。
- 不修改 V4.1 契约（输入/输出格式、字段语义）。
- 不引入 checkpoint、HITL、human-in-the-loop 等高级 LangGraph 特性。

## 4. 必须保留的控制边界

迁移过程中必须保持以下现有约束，不得因框架切换而弱化：

- **代码层终止门槛**：token/轮次/时间上限必须在图节点或状态层显式保留。
- **覆盖完整性**：测试输出必须仍可验证覆盖度指标。
- **V4.1 时间权威**：生成时间戳的逻辑和来源保持不变。
- **错误分类**：现有错误码/异常分类体系继续生效。
- **公开输出过滤**：返回给外部的字段和过滤规则不变。

## 5. 建议迁移阶段

1. 状态/节点映射：将 `IterativeAgent` 的各步骤映射为 LangGraph 节点。
2. 定义 `GraphState`：用 TypedDict 表达状态，字段与现有状态对象对齐。
3. 最小图骨架：构建 `StateGraph`，实现线性流转与条件边。
4. 单视频端到端：选取一个典型视频完成完整流程跑通。
5. golden case 行为对比：与 `IterativeAgent` 输出逐项对比，确保等价。
6. 可选 backend：仅在验证充分后，考虑作为可选 backend 接入 Web API。

## 6. 第一阶段验收标准

- [ ] 本目录下存在最小 LangGraph 图骨架代码。
- [ ] 至少一个典型视频可在新图中端到端跑通。
- [ ] 输出结果与 `IterativeAgent` 的 golden case 一致（字段级 diff 不超过可接受范围）。
- [ ] 不修改现有 CLI/Web 默认路径。
- [ ] 不引入新的外部依赖（若后续需要，将单独评估）。

## 7. 说明

本目录目前仅包含实验目标和阶段规划，**暂不包含任何实现代码**。后续实现请严格遵循上述原则与边界，确保 exploration 与 production 路径安全隔离。
